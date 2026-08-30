import logging
from collections.abc import Iterator
from dataclasses import dataclass

from analytics.services import record_event
from recommendations.scoring import (
    RecommendationRequest,
    ScoredDestination,
    generate_recommendations,
)
from travel.models import Destination
from travel.services import find_destination_slugs_by_name
from trips.models import FEEDBACK_TAG_CHOICES, Feedback, TravelHistoryEntry, Trip

from . import memory
from .prompts import SYSTEM_PROMPT
from .provider import AIMessage, AIProvider, AIProviderError, get_ai_provider

logger = logging.getLogger(__name__)

MAX_EXPLAINED_CANDIDATES = 5
FEEDBACK_TAG_KEYS = {key for key, _label in FEEDBACK_TAG_CHOICES}

OFF_TOPIC_REPLY = (
    "I'm Lunna, TravelAgent's travel consultant, so I can only help with "
    "travel planning. What kind of trip are you thinking about?"
)
NO_MATCHES_REPLY = (
    "I couldn't find a destination that fits everything you're looking for. "
    "Want to relax one of your constraints - dates, budget, or temperature?"
)
FALLBACK_REPLY = (
    "I'm having trouble reaching my reasoning engine right now. Please try again in a moment."
)
NEEDS_LOGIN_REPLY = (
    "I'd love to remember that for you, but you'll need to log in or create an "
    "account first so I can save it to your profile."
)

INTENT_EXTRACTION_SYSTEM_PROMPT = (
    "You classify a traveler's message and extract structured information "
    "from it. Set message_type to exactly one of:\n"
    "- 'recommendation': the user wants a travel suggestion right now.\n"
    "- 'feedback': the user is sharing their opinion or experience about a "
    "place they have already been to (a rating, likes/dislikes, a comment).\n"
    "- 'future_intent': the user names or clearly implies a specific place "
    "they want to visit someday or are planning to, without asking for a "
    "recommendation right now. A message that only states timing (a month, "
    "a season, 'someday', 'sometime soon') with no destination at all is "
    "NOT future_intent, even if it uses the word 'someday' - it is almost "
    "always the user answering what month they want to travel for an "
    "ongoing recommendation request, so classify it as 'recommendation' "
    "instead and extract the month from it.\n"
    "- 'off_topic': the message is not about travel at all.\n"
    "Only fill in the fields relevant to the chosen message_type - leave "
    "every other field at its default (null, false, or an empty list).\n\n"
    "--- Fields for message_type = 'recommendation' ---\n"
    "Set needs_clarification to true, with a short clarification_question, if "
    "the message is a travel request but is missing information you would "
    "need - at minimum, a target month. Never guess a month the user did not "
    "state or clearly imply. If the user names a range of two consecutive "
    "months (e.g. 'September or October', 'between September and October'), "
    "that counts as stating a month - extract the earlier of the two "
    "(September in that example) rather than leaving month null.\n"
    "For temperature and budget, the user will often describe them "
    "qualitatively rather than with an exact number - translate that "
    "description into a concrete threshold using these anchors, so the "
    "application can actually filter on it:\n"
    "- Temperature (min_temp_c): 'hot' -> 28, 'warm' -> 22, 'mild' -> 18. "
    "If the user wants somewhere cool or cold, or says nothing at all about "
    "temperature, leave min_temp_c null.\n"
    "- Budget (max_cost_of_living, a 1-5 scale where 1 is cheapest): "
    "'very cheap'/'budget'/'affordable' -> 2, 'cheap'/'not too expensive'/"
    "'inexpensive' -> 3, 'moderate'/'mid-range' -> 4. If the user wants "
    "luxury, or says nothing at all about budget, leave max_cost_of_living null.\n"
    "Only leave min_temp_c or max_cost_of_living null when the user gave no "
    "indication at all for that dimension - do not leave it null just "
    "because they used words instead of a number.\n"
    "For trip_type, only set it when the message clearly matches one of "
    "exactly these four categories: 'beach' (beach/coastal holiday), "
    "'city' (city break/urban trip), 'nature' (outdoors/adventure/hiking), "
    "'culture' (history/museums/cultural immersion). Leave it null if the "
    "request doesn't clearly match one of these four, or matches more than "
    "one - do not force-fit a vibe like 'romantic' or 'family-friendly' "
    "into one of these categories just because you have to pick something.\n"
    "If the user asks to avoid or exclude specific places, countries, or "
    "regions, list the place/country names they mentioned in "
    "excluded_place_names (e.g. ['Marrakech', 'Morocco']). Leave it as an "
    "empty list if they mentioned no exclusions.\n\n"
    "--- Fields for message_type = 'feedback' ---\n"
    "feedback_destination_name: the name of the place they're giving "
    "feedback about, as they wrote it. Null if unclear.\n"
    "feedback_rating: a 1-10 rating if the user gave or clearly implied one "
    "(e.g. 'amazing' ~ 9, 'terrible' ~ 2). Null if no sentiment was expressed "
    "at all - never invent a rating from a neutral factual statement.\n"
    "feedback_tags: choose zero or more from exactly these values - "
    "excellent_food, great_value, friendly_locals, beautiful_scenery, "
    "too_crowded, overpriced, poor_weather, hard_to_get_around. Only include "
    "a tag when the message clearly supports it.\n"
    "feedback_comment: a short paraphrase of any free-form remark they made, "
    "or null.\n\n"
    "--- Fields for message_type = 'future_intent' ---\n"
    "future_destination_name: the name of the place they want to visit "
    "someday, as written. Null if unclear."
)

INTENT_SCHEMA = {
    "name": "travel_message",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "message_type": {
                "type": "string",
                "enum": ["recommendation", "feedback", "future_intent", "off_topic"],
            },
            "needs_clarification": {"type": "boolean"},
            "clarification_question": {"type": ["string", "null"]},
            "month": {"type": ["integer", "null"]},
            "min_temp_c": {"type": ["number", "null"]},
            "max_cost_of_living": {"type": ["integer", "null"]},
            "trip_type": {
                "type": ["string", "null"],
                "enum": ["beach", "city", "nature", "culture", None],
            },
            "excluded_place_names": {"type": "array", "items": {"type": "string"}},
            "feedback_destination_name": {"type": ["string", "null"]},
            "feedback_rating": {"type": ["integer", "null"]},
            "feedback_tags": {"type": "array", "items": {"type": "string"}},
            "feedback_comment": {"type": ["string", "null"]},
            "future_destination_name": {"type": ["string", "null"]},
        },
        "required": [
            "message_type",
            "needs_clarification",
            "clarification_question",
            "month",
            "min_temp_c",
            "max_cost_of_living",
            "trip_type",
            "excluded_place_names",
            "feedback_destination_name",
            "feedback_rating",
            "feedback_tags",
            "feedback_comment",
            "future_destination_name",
        ],
        "additionalProperties": False,
    },
}


@dataclass(frozen=True)
class OrchestrationResult:
    reply: str
    needs_clarification: bool
    recommendations: list[ScoredDestination]


@dataclass(frozen=True)
class StreamingOrchestrationResult:
    needs_clarification: bool
    recommendations: list[ScoredDestination]
    reply_chunks: Iterator[str]


def stream_travel_recommendation(
    message: str,
    *,
    user=None,
    session_key: str | None = None,
    ai_provider: AIProvider | None = None,
    climate_provider=None,
) -> StreamingOrchestrationResult:
    """Handle one chat message: a recommendation request, feedback about a
    past visit, a stated future travel intention, or an off-topic message.

    Pipeline (09_AI_ORCHESTRATION.md §3): Intent Understanding -> (per type)
    Travel Data + Rules & Constraints -> Recommendation Scoring -> AI
    Reasoning (streamed), OR direct persistence + a templated acknowledgment
    for feedback/future_intent - those don't need a second AI call. This is
    the core orchestration logic; get_travel_recommendation() is a
    non-streaming convenience wrapper around it.

    Conversation memory (09_AI_ORCHESTRATION.md §7, added 2026-08-30): prior
    turns for this conversation (see ai.memory) are loaded and passed to
    intent extraction, so a short follow-up reply - "someday between
    september and october" answering an earlier "what month?" - can be
    understood in context instead of being (mis)classified in isolation.
    `session_key` identifies an anonymous visitor's conversation (there is
    no other stable identity for them); authenticated users are identified
    by their account instead, regardless of session. Every branch below
    appends its own (message, reply) turn before returning, including
    failure/fallback paths, so the next message still has full context.
    This is deliberately conversation *context* only (what's needed to
    understand the current exchange) - not persistent traveler memory,
    which continues to mean TravelerProfile/Feedback/TravelHistoryEntry.

    Recommendation philosophy (decided 2026-08-29, Phase 11 review): a real
    user will ask for things this system has no deterministic model for
    (e.g. "romantic", "family-friendly"). Rather than trying to predict
    every such category in advance, unmatched dimensions are deliberately
    left for the AI to reason about using its own general knowledge - see
    the "do not force-fit" instruction in INTENT_EXTRACTION_SYSTEM_PROMPT.
    What this function does do is *log* those cases (and genuine failures),
    so real usage can inform which dimensions are worth formalizing later
    - "the profile should grow organically as the product learns" applies
    here too, not just to TravelerProfile.
    """
    ai_provider = ai_provider or get_ai_provider()
    conv_key = memory.conversation_key(user=user, session_key=session_key)
    history = memory.get_history(conv_key)

    def _remember(reply: str) -> None:
        memory.append_turn(conv_key, user_message=message, assistant_reply=reply)

    try:
        intent = _extract_intent(message, ai_provider=ai_provider, history=history)
    except AIProviderError:
        logger.warning("Could not extract intent - AI provider failure. message=%r", message)
        _remember(FALLBACK_REPLY)
        return StreamingOrchestrationResult(False, [], iter([FALLBACK_REPLY]))

    message_type = intent["message_type"]

    if message_type == "off_topic":
        _remember(OFF_TOPIC_REPLY)
        return StreamingOrchestrationResult(False, [], iter([OFF_TOPIC_REPLY]))

    if message_type == "feedback":
        reply = _handle_feedback(intent, user=user)
        _remember(reply)
        return StreamingOrchestrationResult(False, [], iter([reply]))

    if message_type == "future_intent":
        reply = _handle_future_intent(intent, user=user)
        _remember(reply)
        return StreamingOrchestrationResult(False, [], iter([reply]))

    # message_type == "recommendation" (also the safe default/fallback).
    if intent["needs_clarification"]:
        question = intent["clarification_question"] or "Could you tell me more about your trip?"
        _remember(question)
        return StreamingOrchestrationResult(True, [], iter([question]))

    no_deterministic_constraints = (
        intent["trip_type"] is None
        and intent["min_temp_c"] is None
        and intent["max_cost_of_living"] is None
    )
    if no_deterministic_constraints:
        # None of our deterministic dimensions matched - the AI will answer
        # entirely from its own reasoning over the unfiltered candidate
        # list. Not an error, but worth knowing about for future review.
        logger.info(
            "No deterministic constraints extracted - relying on AI judgment. message=%r month=%s",
            message,
            intent["month"],
        )

    request = RecommendationRequest(
        month=intent["month"],
        min_temp_c=intent["min_temp_c"],
        max_cost_of_living=intent["max_cost_of_living"],
        trip_type=intent["trip_type"],
        excluded_slugs=find_destination_slugs_by_name(intent["excluded_place_names"]),
        user=user,
    )
    results = generate_recommendations(request, climate_provider=climate_provider)

    if not results:
        logger.info(
            "No destinations matched constraints. message=%r month=%s min_temp_c=%s "
            "max_cost_of_living=%s trip_type=%s",
            message,
            intent["month"],
            intent["min_temp_c"],
            intent["max_cost_of_living"],
            intent["trip_type"],
        )
        _remember(NO_MATCHES_REPLY)
        return StreamingOrchestrationResult(False, [], iter([NO_MATCHES_REPLY]))

    messages = _build_explanation_messages(message, results)

    def _stream_explanation():
        collected = []
        try:
            for chunk in ai_provider.stream_reply(messages):
                collected.append(chunk)
                yield chunk
        except AIProviderError:
            # A partial reply may already have been yielded before a
            # mid-stream failure (09_AI_ORCHESTRATION.md §12: "Interrupted
            # streams" must be handled) - appending the fallback message is
            # an acceptable degrade rather than losing the request entirely.
            logger.warning(
                "AI provider failed mid-stream while explaining results. message=%r", message
            )
            collected.append(FALLBACK_REPLY)
            yield FALLBACK_REPLY
        finally:
            # Runs even if the caller never fully consumes the stream (e.g.
            # the client disconnects) - the conversation still gets
            # whatever was produced, partial or complete, rather than
            # silently losing this turn from memory.
            _remember("".join(collected))

    return StreamingOrchestrationResult(False, results, _stream_explanation())


def get_travel_recommendation(
    message: str,
    *,
    user=None,
    session_key: str | None = None,
    ai_provider: AIProvider | None = None,
    climate_provider=None,
) -> OrchestrationResult:
    """Non-streaming convenience wrapper around stream_travel_recommendation() -
    joins all chunks into one string. Useful for tests and any caller that
    doesn't need incremental output.
    """
    streaming_result = stream_travel_recommendation(
        message,
        user=user,
        session_key=session_key,
        ai_provider=ai_provider,
        climate_provider=climate_provider,
    )
    reply = "".join(streaming_result.reply_chunks)
    return OrchestrationResult(
        reply, streaming_result.needs_clarification, streaming_result.recommendations
    )


def _handle_feedback(intent: dict, *, user) -> str:
    """Persist feedback shared conversationally, and register that the
    trip actually happened - giving feedback implies a visit occurred, per
    the user's explicit request that the AI register travel that occurred."""
    destination_name = intent["feedback_destination_name"]
    if not destination_name:
        # Ask before gating on login: we don't yet know there's anything
        # real to save, so there's nothing to require an account for. Also
        # a safety net against an intent misclassification (e.g. a
        # timing-only message that isn't really feedback at all) leaving
        # an anonymous user stuck behind a login wall for no reason - the
        # chat should never dead-end just because of that.
        return "I'd love to hear about your trip - which destination are you talking about?"

    if user is None or not user.is_authenticated:
        return NEEDS_LOGIN_REPLY

    destination = _resolve_destination(destination_name)
    if destination is None:
        logger.info("Feedback mentioned an unrecognized destination. name=%r", destination_name)
        return (
            f"I don't have {destination_name} in my catalog yet, but thanks for sharing - "
            "I've made a note of it!"
        )

    # Register that this travel occurred, regardless of whether a rating was given.
    TravelHistoryEntry.objects.get_or_create(user=user, destination=destination)

    rating = intent["feedback_rating"]
    if rating is None:
        return (
            f"Got it - I've noted that you've visited {destination.name}. Feel free to tell me "
            "how you'd rate it (1-10) if you'd like!"
        )

    Feedback.objects.update_or_create(
        user=user,
        destination=destination,
        trip=None,
        defaults={
            "rating": rating,
            "tags": intent["feedback_tags"],
            "comment": intent["feedback_comment"] or "",
        },
    )
    record_event(
        "feedback_submitted",
        user=user,
        metadata={"destination_slug": destination.slug, "rating": rating, "source": "chat"},
    )
    return f"Thanks! I've recorded your feedback on {destination.name}: {rating}/10."


def _handle_future_intent(intent: dict, *, user) -> str:
    destination_name = intent["future_destination_name"]
    if not destination_name:
        # Same reasoning as _handle_feedback: don't gate on login before
        # confirming there's an actual destination to save - keeps the
        # chat going instead of dead-ending on a misclassified message.
        return "That sounds exciting - which destination did you have in mind?"

    if user is None or not user.is_authenticated:
        return NEEDS_LOGIN_REPLY

    destination = _resolve_destination(destination_name)
    if destination is None:
        logger.info(
            "Future travel intent mentioned an unrecognized destination. name=%r", destination_name
        )
        return (
            f"I don't have {destination_name} in my catalog yet, but I've made a note that "
            "you'd like to go!"
        )

    _trip, created = Trip.objects.get_or_create(
        user=user,
        destination=destination,
        status="planned",
        defaults={"name": f"Someday: {destination.name}"},
    )
    if created:
        record_event(
            "trip_created",
            user=user,
            metadata={"destination_slug": destination.slug, "status": "planned", "source": "chat"},
        )
        return f"Got it! I've added {destination.name} to your trips to plan for someday."
    return f"You already have {destination.name} noted as a future trip - I'll keep it there!"


def _resolve_destination(name: str):
    slugs = find_destination_slugs_by_name([name])
    return Destination.objects.filter(slug__in=slugs).first()


def _extract_intent(
    message: str, *, ai_provider: AIProvider, history: list[dict] | None = None
) -> dict:
    messages = [AIMessage(role="system", content=INTENT_EXTRACTION_SYSTEM_PROMPT)]
    messages.extend(
        AIMessage(role=turn["role"], content=turn["content"]) for turn in history or []
    )
    messages.append(AIMessage(role="user", content=message))
    data = ai_provider.generate_structured_reply(messages, json_schema=INTENT_SCHEMA)
    return _validate_intent(data)


def _validate_intent(data: dict) -> dict:
    # Response Validation (09_AI_ORCHESTRATION.md §9): never trust the
    # model's structured output blindly, even with a schema.
    if data.get("message_type") not in {"recommendation", "feedback", "future_intent", "off_topic"}:
        data["message_type"] = "recommendation"

    month = data.get("month")
    if not isinstance(month, int) or not (1 <= month <= 12):
        data["month"] = None
        if data.get("message_type") == "recommendation" and not data.get("needs_clarification"):
            data["needs_clarification"] = True
            data["clarification_question"] = (
                data.get("clarification_question") or "Which month are you thinking of traveling?"
            )

    max_cost_of_living = data.get("max_cost_of_living")
    if max_cost_of_living is not None and not (1 <= max_cost_of_living <= 5):
        data["max_cost_of_living"] = None

    if data.get("trip_type") not in {"beach", "city", "nature", "culture", None}:
        data["trip_type"] = None

    data["excluded_place_names"] = _clean_string_list(data.get("excluded_place_names"))

    feedback_rating = data.get("feedback_rating")
    if feedback_rating is not None and not (1 <= feedback_rating <= 10):
        data["feedback_rating"] = None

    cleaned_tags = _clean_string_list(data.get("feedback_tags"))
    data["feedback_tags"] = [tag for tag in cleaned_tags if tag in FEEDBACK_TAG_KEYS]

    return data


def _clean_string_list(value) -> list:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def _build_explanation_messages(
    message: str, results: list[ScoredDestination]
) -> list[AIMessage]:
    top_results = results[:MAX_EXPLAINED_CANDIDATES]
    candidates_summary = "\n".join(
        f"- {r.destination.name}, {r.destination.country}: avg high {r.avg_high_c}C, "
        f"cost tier {r.destination.cost_of_living}/5, trip type {r.destination.trip_type}"
        for r in top_results
    )

    return [
        AIMessage(role="system", content=SYSTEM_PROMPT),
        AIMessage(
            role="user",
            content=(
                f'The traveler asked: "{message}"\n\n'
                "Here are the top matching destinations, already filtered and "
                "ranked by the application. Do not invent any other destinations "
                "or facts beyond what is listed here:\n"
                f"{candidates_summary}\n\n"
                "Write a short, natural reply recommending the best 1-3 options "
                "and briefly explain why each fits."
            ),
        ),
    ]
