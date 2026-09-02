import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date

from analytics.services import record_event
from recommendations.scoring import (
    RecommendationRequest,
    ScoredDestination,
    generate_recommendations,
)
from travel.models import COST_OF_LIVING_CHOICES, TRIP_TYPE_CHOICES, Destination
from travel.services import (
    ENTRY_REQUIREMENT_DISCLAIMER,
    find_destination_slugs_by_name,
    get_entry_requirements,
)
from trips.models import FEEDBACK_TAG_CHOICES, Feedback, TravelHistoryEntry, Trip
from users.currency import convert_to_usd
from users.models import TravelerProfile

from . import memory
from .prompts import SYSTEM_PROMPT
from .provider import AIMessage, AIProvider, AIProviderError, get_ai_provider

logger = logging.getLogger(__name__)

# Renamed from MAX_EXPLAINED_CANDIDATES and bumped 5 -> 10 (2026-09-02,
# direct user request: cap recommendations at 10 "no maximo" so token
# spend and the number of options a traveler has to sift through both
# stay bounded, even against the 384-destination catalog now capable of
# returning dozens of matches on a single broad trip_type). One constant
# governs both how many candidates the AI ever sees/explains and how many
# recommendation cards ever reach the UI, kept in sync deliberately - see
# stream_travel_recommendation, which slices `results` to this exactly
# once before either consumer sees them.
MAX_RECOMMENDATIONS = 10
FEEDBACK_TAG_KEYS = {key for key, _label in FEEDBACK_TAG_CHOICES}
# Derived from travel.models rather than hardcoded here a second time -
# these used to be an independent copy of the choices list, which could
# silently desync from the actual Destination.trip_type/cost_of_living
# choices (found in a 2026-09-02 review). travel.models is the canonical
# source since it owns the destination catalog these fields describe.
TRIP_TYPE_CODES = [code for code, _label in TRIP_TYPE_CHOICES]
MAX_COST_OF_LIVING_TIER = len(COST_OF_LIVING_CHOICES)

FALLBACK_REPLY = (
    "I'm having trouble reaching my reasoning engine right now. Please try again in a moment."
)
NEEDS_LOGIN_REPLY = (
    "I'd love to remember that for you, but you'll need to log in or create an "
    "account first so I can save it to your profile."
)

INTENT_EXTRACTION_SYSTEM_PROMPT = (
    "You classify a traveler's message and extract structured information "
    "from it. Judge message_type using ONLY what the CURRENT message itself "
    "says - conversation history is context to help you understand the "
    "current message (e.g. what a vague reply is answering), never a "
    "pattern to keep repeating. If an earlier message was off_topic or "
    "unclear, that has no bearing on how you classify this new message; "
    "re-read this message on its own merits every time. Set message_type "
    "to exactly one of:\n"
    "- 'recommendation': the user wants a travel suggestion right now - "
    "this includes short, plain expressions of wanting to travel with no "
    "other detail yet (e.g. 'I want to travel', 'quero viajar', 'I need a "
    "vacation'). These are real, if incomplete, travel requests - almost "
    "never off_topic.\n"
    "- 'feedback': the user is describing a place THEY THEMSELVES have "
    "personally already visited - a rating, likes/dislikes, a comment "
    "about a trip they took. This requires a clear signal that they are "
    "recounting their own past visit (e.g. past tense - 'fui a', 'visitei', "
    "'estive em', 'I went to', 'we stayed in', 'when I was there') AND a "
    "specific place. A request for the assistant to evaluate, rank, rate, "
    "or list places in general (e.g. 'what are the 5 worst places to visit "
    "in winter', 'quais os piores destinos') is NEVER feedback, even though "
    "it uses evaluative words like 'worst' or 'rate' - the user is asking "
    "FOR information, not GIVING an account of their own trip. That is "
    "'recommendation' instead (see below - it covers any request for "
    "travel information or suggestions, not just positive ones).\n"
    "- 'future_intent': the user, unprompted, brings up an actual place (a "
    "city, country, or region) as their own standing goal or plan to visit "
    "someday, without asking for a recommendation right now (e.g. 'I've "
    "always wanted to see Kyoto', 'planejo ir para o Chile um dia'). This "
    "requires a real named destination AND the user themselves introducing "
    "it as a personal intent - wanting to travel, changing your mind, or "
    "expressing eagerness/excitement is not future_intent by itself, and "
    "neither is simply naming a place. A message that only states timing "
    "(a month, a season, 'someday', 'sometime soon') or only expresses "
    "wanting or deciding to travel with no destination named at all (e.g. "
    "'I want to go', 'quero viajar', 'mudei de ideia, quero ir em abril' / "
    "'I changed my mind, I want to go in April') is NOT future_intent, "
    "even if it uses words like 'someday' or 'quero' - it is almost always "
    "the user answering or updating what month they want to travel for an "
    "ongoing recommendation request, so classify it as 'recommendation' "
    "instead and extract the month from it. Crucially: if your own "
    "immediately preceding reply just suggested destinations or asked "
    "which of them interests the traveler, and the current message is "
    "just naming one of them (or a short reaction to it, e.g. 'Bahia', "
    "'I like that one', 'tell me more about that one'), that is the "
    "traveler picking from YOUR suggestions to keep narrowing down an "
    "ongoing search - classify it as 'recommendation', not future_intent, "
    "even though a place is named. future_intent is reserved for the "
    "traveler spontaneously raising a place as their own goal, never for "
    "selecting from options you just gave them.\n"
    "- 'off_topic': the message itself is not about travel at all (e.g. a "
    "question about something unrelated, small talk with no travel intent "
    "at all like a bare greeting). Only use this when the message truly "
    "has nothing to do with travel - a vague or short travel-related "
    "message is 'recommendation', not this.\n"
    "When a message is genuinely ambiguous between 'recommendation' and "
    "any other category, prefer 'recommendation' - it is the safest "
    "default (never blocks on login, never dead-ends the conversation) "
    "and keeps things moving toward a real answer; reserve 'feedback' and "
    "'future_intent' for messages that clearly and unambiguously fit their "
    "stricter definitions above.\n"
    "Only fill in the fields relevant to the chosen message_type - leave "
    "every other field at its default (null, false, or an empty list). "
    "The traveler may write in any language - understand it and extract "
    "from it the same way regardless of language.\n"
    "Conversation history, when present, includes your OWN prior replies - "
    "these often mention specific numbers (a destination's exact "
    "temperature, its cost tier) or ask about climate/budget as part of a "
    "question. Never treat a number YOU stated earlier as something the "
    "traveler asked for, and never treat the traveler answering ONE part "
    "of a multi-part question you asked (e.g. picking a trip_type from a "
    "list that also asked about timing and budget) as if they'd also "
    "answered the other parts - if they only said 'praia'/'beach' in "
    "reply to a question that also asked about climate or budget, that "
    "still only sets trip_type; min_temp_c and max_cost_of_living stay "
    "null exactly as they would with zero conversation history at all. "
    "Every field below is extracted only from what the traveler themselves "
    "explicitly wrote, in this message or earlier ones - if they only "
    "reacted to a suggestion (e.g. 'sounds good', a bare month, 'yes') "
    "without restating a preference, do not infer temperature or budget "
    "thresholds from the destinations or questions you happened to "
    "mention.\n\n"
    "--- Fields for message_type = 'recommendation' ---\n"
    "Extract whatever the traveler actually gave you - never ask a "
    "follow-up question and never treat any field as required. A real "
    "person will rarely state every dimension (month, climate, budget, "
    "trip type) in one message, and should never be blocked from getting "
    "a real answer because of that - every field below is optional, and "
    "leaving one null just means the application treats that dimension as "
    "not relevant/unconstrained, not as something missing to chase.\n"
    "month: extract only if stated or clearly implied - never guess one. "
    "If the user names a range of two consecutive months (e.g. 'September "
    "or October', 'between September and October'), extract the earlier "
    "of the two. If no month is stated at all, leave it null - the "
    "application already assumes a reasonable month automatically in that "
    "case, so this is never something to ask about.\n"
    "For temperature and budget, the user will often describe them "
    "qualitatively rather than with an exact number - translate that "
    "description into a concrete threshold using these anchors, so the "
    "application can actually filter on it, but ONLY when the user's own "
    "words actually describe that dimension. A trip_type alone never "
    "implies a temperature or budget, no matter how strongly it's "
    "stereotypically associated with one - 'praia'/'beach' by itself does "
    "NOT mean min_temp_c=28; a beach trip can be mild, off-season, or the "
    "traveler simply may not care about the exact temperature. The same "
    "goes for budget: naming a destination or trip_type never implies a "
    "cost tier by itself. A trip_type combined with a month is still not "
    "a temperature statement - e.g. 'praia em julho'/'beach in July' has "
    "a trip_type and a month but says nothing about temperature, so "
    "min_temp_c stays null; do not reason 'they mentioned a month for a "
    "beach trip, so they probably want to know it'll be warm then' - only "
    "set min_temp_c when the message itself contains a temperature word "
    "or number. Set these two fields only from words that are themselves "
    "about temperature or money:\n"
    "- Temperature (min_temp_c): 'hot' -> 28, 'warm' -> 22, 'mild' -> 18. "
    "If the user wants somewhere cool or cold, or says nothing at all about "
    "temperature, leave min_temp_c null - this includes messages that only "
    "name a trip_type, destination, or month with no temperature words at "
    "all.\n"
    "- Upper temperature bound (max_temp_c): the mirror image of "
    "min_temp_c, for when the user wants an upper limit instead of (or as "
    "well as) a lower one - 'not too hot'/'nothing extreme' -> 30, "
    "'cool'/'mild, not hot' -> 22, 'cold'/'chilly'/'somewhere cool and "
    "crisp' -> 15. Only set this from words that are themselves about an "
    "upper temperature limit or wanting it cool/cold - never infer it from "
    "a trip_type, destination, or month alone, exactly like min_temp_c "
    "above. A message can set both min_temp_c and max_temp_c together "
    "(e.g. 'mild, not too hot and not too cold') or just one.\n"
    "- Budget (max_cost_of_living, a 1-5 scale where 1 is cheapest): "
    "'very cheap'/'budget'/'affordable' -> 2, 'cheap'/'not too expensive'/"
    "'inexpensive' -> 3, 'moderate'/'mid-range' -> 4. If the user wants "
    "luxury, or says nothing at all about budget, leave max_cost_of_living "
    "null - this includes messages that only name a trip_type, "
    "destination, or month with no budget words at all.\n"
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
            "month": {"type": ["integer", "null"]},
            "min_temp_c": {"type": ["number", "null"]},
            "max_temp_c": {"type": ["number", "null"]},
            "max_cost_of_living": {"type": ["integer", "null"]},
            "trip_type": {
                "type": ["string", "null"],
                "enum": [*TRIP_TYPE_CODES, None],
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
            "month",
            "min_temp_c",
            "max_temp_c",
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
    recommendations: list[ScoredDestination]


@dataclass(frozen=True)
class StreamingOrchestrationResult:
    recommendations: list[ScoredDestination]
    reply_chunks: Iterator[str]


def stream_travel_recommendation(
    message: str,
    *,
    user=None,
    session_key: str | None = None,
    ai_provider: AIProvider | None = None,
    climate_provider=None,
    history_override: list[dict] | None = None,
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

    `history_override` (2026-09-02, saved-conversations feature): when the
    caller is continuing a conversation already persisted in
    ai.models.SavedConversation, it passes that conversation's own stored
    messages here instead of relying on ai.memory's Redis-backed short-term
    context - the persisted conversation is a strictly more complete and
    durable source of truth for it than Redis's 30-minute TTL bucket, so
    this function skips reading *and writing* ai.memory entirely for that
    call, leaving Redis memory exclusively for conversations that are not
    (or not yet) saved.
    """
    ai_provider = ai_provider or get_ai_provider()
    profile = _traveler_profile(user)
    if history_override is not None:
        conv_key = None
        history = history_override
    else:
        conv_key = memory.conversation_key(user=user, session_key=session_key)
        history = memory.get_history(conv_key)

    def _remember(reply: str) -> None:
        if conv_key is not None:
            memory.append_turn(conv_key, user_message=message, assistant_reply=reply)

    try:
        intent = _extract_intent(message, ai_provider=ai_provider, history=history)
    except AIProviderError:
        logger.warning("Could not extract intent - AI provider failure. message=%r", message)
        _remember(FALLBACK_REPLY)
        return StreamingOrchestrationResult([], iter([FALLBACK_REPLY]))

    message_type = intent["message_type"]

    if message_type == "off_topic":
        # Real AI reply (2026-08-30, direct user feedback: this returning
        # the exact same fixed sentence for every unrelated message - even
        # "are you an AI?" - was the clearest sign the assistant "doesn't
        # feel like an AI, just an if/else". SYSTEM_PROMPT already tells it
        # how to handle this naturally; just hand it the message.
        off_topic_messages = _build_off_topic_messages(message, history)
        off_topic_reply = _stream_ai_reply(
            off_topic_messages, message, ai_provider=ai_provider, remember=_remember
        )
        return StreamingOrchestrationResult([], off_topic_reply)

    if message_type == "feedback":
        # Same pattern as future_intent below - _handle_feedback returns
        # None specifically for a real destination our curated catalog
        # doesn't have (2026-09-02 review: this used to be the one
        # remaining canned "I don't have it, but I've noted it" dead end,
        # inconsistent with the fix already applied to future_intent for
        # the identical underlying situation).
        quick_feedback_reply = _handle_feedback(
            intent, user=user, message=message, history=history, ai_provider=ai_provider
        )
        if quick_feedback_reply is not None:
            _remember(quick_feedback_reply)
            return StreamingOrchestrationResult([], iter([quick_feedback_reply]))

        unrecognized_feedback_messages = _build_unrecognized_feedback_destination_messages(
            message, intent["feedback_destination_name"], history
        )
        unrecognized_feedback_reply = _stream_ai_reply(
            unrecognized_feedback_messages, message, ai_provider=ai_provider, remember=_remember
        )
        return StreamingOrchestrationResult([], unrecognized_feedback_reply)

    if message_type == "future_intent":
        # _handle_future_intent returns None specifically when the named
        # destination is real but not in our curated catalog - there's no
        # Destination row to attach a Trip to (never invent catalog data,
        # 05_AI_DESIGN.md §7), but per direct user feedback 2026-09-02 ("se
        # nao estiver no catalogo ele deve usar o conhecimento da IA" - a
        # bare "I don't have it in my catalog, but I've noted it" reply
        # was unhelpful and contradicted the Phase 11 recommendation
        # philosophy) that case now gets a real AI reply from general
        # knowledge instead of a canned acknowledgment, same as an
        # unmatched recommendation request already does.
        quick_reply = _handle_future_intent(
            intent, user=user, message=message, history=history, ai_provider=ai_provider
        )
        if quick_reply is not None:
            _remember(quick_reply)
            return StreamingOrchestrationResult([], iter([quick_reply]))

        unrecognized_messages = _build_unrecognized_future_destination_messages(
            message, intent["future_destination_name"], history
        )
        unrecognized_reply = _stream_ai_reply(
            unrecognized_messages, message, ai_provider=ai_provider, remember=_remember
        )
        return StreamingOrchestrationResult([], unrecognized_reply)

    # message_type == "recommendation" (also the safe default/fallback).
    # No clarification gate here on purpose (removed 2026-08-30, per direct
    # user feedback): a real user will rarely state every dimension in one
    # message, and should never be blocked from a real answer for it -
    # month is defaulted below if missing, and every other field already
    # treats "unspecified" as "not relevant" rather than "missing".
    #
    # min_temp_c/max_cost_of_living are strong signals on their own - a
    # traveler rarely states an explicit temperature or budget without
    # real intent, so either one alone is enough to search immediately.
    # trip_type alone now also counts on its own (2026-09-02, direct user
    # feedback on a real transcript: asking for beach destinations with no
    # other detail kept getting an endless gathering quiz instead of any
    # answer - "a prioridade da IA deve ser sempre responder a pergunta do
    # usuario quando for cabivel" / the AI's priority should always be to
    # answer the user's question when feasible). This deliberately
    # reopens a narrower 2026-08-31 decision (trip_type required a
    # co-stated month too, reacting to "gosto de praias" jumping to
    # suggestions when the 18-destination catalog gave almost nothing to
    # differentiate by) - the catalog is 384 destinations now (2026-09-02
    # expansion), so trip_type alone is real, meaningful signal again, not
    # a near-unfiltered dump. A bare month (stated or defaulted) or an
    # exclusion alone still isn't enough on its own - the 2026-08-31 fix
    # for "throwing destinations in the user's face" off a bare "help me
    # plan a year-end trip" still applies, since neither of those actually
    # differentiates anything by itself the way a trip_type does. Route
    # through the same AI-judgment "ask a genuine follow-up, or suggest if
    # they've explicitly invited a guess" path used for a fully blank
    # opener, unless there's actually enough to differentiate on.
    has_enough_signal = (
        intent["min_temp_c"] is not None
        or intent["max_temp_c"] is not None
        or intent["max_cost_of_living"] is not None
        or intent["trip_type"] is not None
    )
    if not has_enough_signal:
        logger.info(
            "Not enough signal yet to differentiate destinations - letting the AI keep "
            "gathering information instead of running an unfiltered search. message=%r "
            "month=%s trip_type=%s",
            message,
            intent["month"],
            intent["trip_type"],
        )
        open_ended_messages = _build_open_ended_messages(message, intent, history, profile)
        open_ended_reply = _stream_ai_reply(
            open_ended_messages, message, ai_provider=ai_provider, remember=_remember
        )
        return StreamingOrchestrationResult([], open_ended_reply)

    # Confirm profile-derived context before suggesting anything (2026-09-02,
    # direct user request: "IA must always confirm this information with the
    # user before suggest any destination") - stored TravelerProfile details
    # could be stale for THIS trip (a solo traveler last time, a group now;
    # an old budget), so they're never used to shape a suggestion silently.
    # Gated to once per conversation via a small Redis flag (separate from
    # ai.memory's own turn history, and computed the same way regardless of
    # history_override, so saved conversations get this exactly once too) -
    # asking every single message would reintroduce the friction this
    # module has deliberately removed everywhere else; the next message
    # proceeds straight to real suggestions regardless of how the traveler
    # answered, matching that same low-friction philosophy.
    confirmation_key = memory.conversation_key(user=user, session_key=session_key)
    if _has_confirmable_profile_data(profile) and not memory.is_profile_confirmed(
        confirmation_key
    ):
        memory.mark_profile_confirmed(confirmation_key)
        confirmation_messages = _build_profile_confirmation_messages(message, profile, history)
        confirmation_reply = _stream_ai_reply(
            confirmation_messages, message, ai_provider=ai_provider, remember=_remember
        )
        return StreamingOrchestrationResult([], confirmation_reply)

    request = RecommendationRequest(
        month=intent["month"],
        min_temp_c=intent["min_temp_c"],
        max_temp_c=intent["max_temp_c"],
        max_cost_of_living=intent["max_cost_of_living"],
        trip_type=intent["trip_type"],
        excluded_slugs=find_destination_slugs_by_name(intent["excluded_place_names"]),
        user=user,
    )
    results = generate_recommendations(request, climate_provider=climate_provider)

    if not results:
        logger.info(
            "No destinations matched constraints. message=%r month=%s min_temp_c=%s "
            "max_temp_c=%s max_cost_of_living=%s trip_type=%s",
            message,
            intent["month"],
            intent["min_temp_c"],
            intent["max_temp_c"],
            intent["max_cost_of_living"],
            intent["trip_type"],
        )
        # Rather than a dead-end canned reply, let the AI try to actually
        # help - reason from its own general knowledge (same recommendation
        # philosophy already approved for vibes our deterministic model
        # doesn't cover, Phase 11), treating whichever constraint made
        # everything unmatchable as relaxable rather than blocking (direct
        # user feedback, 2026-08-30: never just ask for more when the app
        # can attempt a real answer instead).
        no_match_messages = _build_no_matches_messages(message, intent, history, profile)
        no_match_reply = _stream_ai_reply(
            no_match_messages, message, ai_provider=ai_provider, remember=_remember
        )
        return StreamingOrchestrationResult([], no_match_reply)

    # Capped once, here, before either consumer (the AI's own prompt and
    # ai/views.py's recommendation cards) ever sees `results` - 2026-09-02,
    # direct user request, since a broad trip_type-only match (the same-day
    # fix a few entries above) can now return dozens of real candidates
    # against the 384-destination catalog. total_matches (the real,
    # uncapped count) is kept so the explanation can honestly tell the
    # traveler there's more available if they narrow the request further,
    # rather than silently presenting 10 as if that were the whole story.
    total_matches = len(results)
    results = results[:MAX_RECOMMENDATIONS]

    messages = _build_explanation_messages(
        message,
        results,
        history,
        month_was_assumed=intent["month_was_assumed"],
        month=intent["month"],
        profile=profile,
        total_matches=total_matches,
    )
    return StreamingOrchestrationResult(
        results,
        _stream_ai_reply(messages, message, ai_provider=ai_provider, remember=_remember),
    )


def _stream_ai_reply(
    messages: list[AIMessage], message: str, *, ai_provider: AIProvider, remember
) -> Iterator[str]:
    """Stream one AI reply, saving the full text to conversation memory once
    fully produced (or on a mid-stream failure) - shared by both the normal
    recommendation-explanation path and the no-matches path above, since
    both need the same streaming/fallback/memory behavior."""
    collected = []
    try:
        for chunk in ai_provider.stream_reply(messages):
            collected.append(chunk)
            yield chunk
    except AIProviderError:
        # A partial reply may already have been yielded before a mid-stream
        # failure (09_AI_ORCHESTRATION.md §12: "Interrupted streams" must be
        # handled) - appending the fallback message is an acceptable degrade
        # rather than losing the request entirely.
        logger.warning("AI provider failed mid-stream. message=%r", message)
        collected.append(FALLBACK_REPLY)
        yield FALLBACK_REPLY
    finally:
        # Runs even if the caller never fully consumes the stream (e.g. the
        # client disconnects) - the conversation still gets whatever was
        # produced, partial or complete, rather than silently losing this
        # turn from memory.
        remember("".join(collected))


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
    return OrchestrationResult(reply, streaming_result.recommendations)


def _localize_reply(
    fact: str, *, message: str, history: list[dict] | None = None, ai_provider: AIProvider
) -> str:
    """Phrase a fixed, already-decided confirmation in the traveler's own
    language and tone, via one small non-streaming AI call.

    Feedback/future-intent acknowledgments (_handle_feedback,
    _handle_future_intent below) were deliberately templated, non-AI
    strings (2026-08-29 - "no need for a second AI call for these
    confirmations"), which meant they stayed hardcoded English even in an
    otherwise fully Portuguese conversation - a real inconsistency found
    live during the 2026-08-31 AI-intelligence testing pass. Raised with
    the user as a product decision (this reopens that 2026-08-29 choice,
    not a pure bug) rather than fixed unilaterally; the user chose to
    accept the extra AI call over the language inconsistency. This call
    only *phrases* a fact the application has already fully decided (what
    changed, whether it succeeded) - it is never asked to decide anything
    itself, unlike every other AI call in this module.
    """
    messages = [AIMessage(role="system", content=SYSTEM_PROMPT)]
    messages.extend(_history_messages(history))
    messages.append(
        AIMessage(
            role="user",
            content=(
                f'The traveler just wrote: "{message}"\n\n'
                "Say exactly this, in your own natural words, in the same "
                "language the traveler has been using in this conversation "
                "(check the history above if this message alone is short "
                "or ambiguous, e.g. just a name) - this applies just as "
                f"much to English as to any other language: {fact}"
            ),
        )
    )
    try:
        return ai_provider.generate_reply(messages).content
    except AIProviderError:
        # Degrade to the correct-but-unlocalized English fact rather than
        # losing the confirmation entirely - the traveler still learns
        # what happened, just not in their own language this one time.
        logger.warning("Could not localize confirmation reply - using it as-is. fact=%r", fact)
        return fact


def _handle_feedback(
    intent: dict,
    *,
    user,
    message: str,
    history: list[dict] | None = None,
    ai_provider: AIProvider,
) -> str | None:
    """Persist feedback shared conversationally, and register that the
    trip actually happened - giving feedback implies a visit occurred, per
    the user's explicit request that the AI register travel that occurred.

    Returns None specifically when the traveler gave feedback about a
    real destination our curated catalog doesn't have - see
    _handle_future_intent's docstring for the identical pattern; the
    caller (stream_travel_recommendation) then builds a real AI reply
    from general knowledge instead of a canned acknowledgment."""
    destination_name = intent["feedback_destination_name"]
    if not destination_name:
        # Ask before gating on login: we don't yet know there's anything
        # real to save, so there's nothing to require an account for. Also
        # a safety net against an intent misclassification (e.g. a
        # timing-only message that isn't really feedback at all) leaving
        # an anonymous user stuck behind a login wall for no reason - the
        # chat should never dead-end just because of that.
        return _localize_reply(
            "I'd love to hear about your trip - which destination are you talking about?",
            message=message,
            history=history,
            ai_provider=ai_provider,
        )

    if user is None or not user.is_authenticated:
        return _localize_reply(
            NEEDS_LOGIN_REPLY, message=message, history=history, ai_provider=ai_provider
        )

    destination = _resolve_destination(destination_name)
    if destination is None:
        # 2026-09-02 review: previously a canned "I don't have it in my
        # catalog, but thanks for sharing" reply here - the same dead-end
        # pattern already fixed for future_intent, for the identical
        # reason (no valid Destination row exists to register the visit
        # against - TravelHistoryEntry.destination is a real FK, and
        # inventing one would violate 05_AI_DESIGN.md §7).
        logger.info(
            "Feedback mentioned an unrecognized destination - answering from general "
            "knowledge instead of a canned note. name=%r",
            destination_name,
        )
        return None

    # Register that this travel occurred, regardless of whether a rating was given.
    TravelHistoryEntry.objects.get_or_create(user=user, destination=destination)

    rating = intent["feedback_rating"]
    if rating is None:
        return _localize_reply(
            f"Got it - I've noted that you've visited {destination.name}. Feel free to tell me "
            "how you'd rate it (1-10) if you'd like!",
            message=message,
            history=history,
            ai_provider=ai_provider,
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
    return _localize_reply(
        f"Thanks! I've recorded your feedback on {destination.name}: {rating}/10.",
        message=message,
        history=history,
        ai_provider=ai_provider,
    )


def _handle_future_intent(
    intent: dict,
    *,
    user,
    message: str,
    history: list[dict] | None = None,
    ai_provider: AIProvider,
) -> str | None:
    """Returns None specifically when the traveler named a real, valid
    destination that just isn't in our curated catalog - the caller
    (stream_travel_recommendation) then builds a real AI reply from
    general knowledge instead of the quick templated acknowledgments
    every other case here returns directly."""
    destination_name = intent["future_destination_name"]
    if not destination_name:
        # Same reasoning as _handle_feedback: don't gate on login before
        # confirming there's an actual destination to save - keeps the
        # chat going instead of dead-ending on a misclassified message.
        return _localize_reply(
            "That sounds exciting - which destination did you have in mind?",
            message=message,
            history=history,
            ai_provider=ai_provider,
        )

    if user is None or not user.is_authenticated:
        return _localize_reply(
            NEEDS_LOGIN_REPLY, message=message, history=history, ai_provider=ai_provider
        )

    destination = _resolve_destination(destination_name)
    if destination is None:
        # 2026-09-02, direct user feedback: a canned "I don't have it in
        # my catalog, but I've noted it" reply here was unhelpful and
        # contradicted the Phase 11 recommendation philosophy (reason from
        # general knowledge when the curated data doesn't cover
        # something) - the caller now handles this with a real AI reply
        # instead. No Trip can be persisted either way (Trip.destination
        # is a real FK; there's no valid Destination row for it - never
        # invent catalog data, 05_AI_DESIGN.md §7).
        logger.info(
            "Future travel intent mentioned an unrecognized destination - answering from "
            "general knowledge instead of a canned note. name=%r",
            destination_name,
        )
        return None

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
        return _localize_reply(
            f"Got it! I've added {destination.name} to your trips to plan for someday.",
            message=message,
            history=history,
            ai_provider=ai_provider,
        )
    return _localize_reply(
        f"You already have {destination.name} noted as a future trip - I'll keep it there!",
        message=message,
        history=history,
        ai_provider=ai_provider,
    )


def _resolve_destination(name: str):
    slugs = find_destination_slugs_by_name([name])
    return Destination.objects.filter(slug__in=slugs).first()


def _history_messages(history: list[dict] | None) -> list[AIMessage]:
    """Turn stored conversation-memory turns (ai.memory) into AIMessages.

    Shared by every AI call in this module, not just intent extraction
    (2026-08-31, found live: a reply-generation call given only the
    current message - no history - had no way to tell what language the
    conversation had been in when that message was itself ambiguous, e.g.
    a bare destination name like "Bahia"; it silently answered in English
    mid a Portuguese conversation). Every call the traveler can perceive
    as part of one conversation should actually see that conversation.
    """
    return [AIMessage(role=turn["role"], content=turn["content"]) for turn in history or []]


def _traveler_profile(user) -> TravelerProfile | None:
    """The signed-in traveler's profile, or None (anonymous, no profile
    row yet, or no relevant fields set) - a cheap lookup shared by every
    prompt builder that wants to factor in home_country/travelers_count/
    budget (2026-09-02, direct user request to actually use this data,
    not just collect it). Does not raise on a missing profile - the same
    "not filled in yet" treatment every other optional field here gets."""
    if user is None or not user.is_authenticated:
        return None
    return TravelerProfile.objects.filter(user=user).first()


def _has_confirmable_profile_data(profile: TravelerProfile | None) -> bool:
    """Whether there's anything on the traveler's profile worth confirming
    before suggesting a destination (2026-09-02) - mirrors exactly which
    fields _traveler_context_note below would actually mention, so the
    confirmation gate in stream_travel_recommendation never fires for a
    profile that has nothing to confirm in the first place."""
    if profile is None:
        return False
    return bool(
        profile.home_country
        or profile.travelers_count
        or (profile.budget_amount and profile.budget_period and profile.budget_currency)
    )


def _traveler_context_note(profile: TravelerProfile | None) -> str:
    """A short free-text note the AI can factor into its reasoning when
    relevant - never a hard constraint (recommendations.scoring's hard
    filters stay message-only, per RecommendationRequest). budget_amount
    is only ever handed over converted to an approximate USD figure
    (2026-09-02, direct follow-up request: "budget must be always on
    dolar... the agent must also check for this currency in dolar and
    convert to estimate") via users.currency.convert_to_usd - never the
    raw currency-ambiguous number, and always explicitly labeled as a
    rough estimate rather than a precise constraint, the same "let the AI
    reason from what's actually known, don't invent precision"
    philosophy already applied to every other dimension in this module."""
    if profile is None:
        return ""
    bits = []
    if profile.home_country:
        bits.append(f"traveling from {profile.home_country}")
    if profile.travelers_count:
        bits.append(
            f"usually travels with {profile.travelers_count} "
            "people total (including themselves)"
        )
    if profile.budget_amount and profile.budget_period and profile.budget_currency:
        # Deliberately a separate, lowercase, mid-sentence phrasing rather
        # than reusing BUDGET_PERIOD_CHOICES's form-label text ("Per day")
        # directly - that capitalization only reads naturally as a select
        # option, not inline in a sentence ("... per Per day" was the bug
        # this local map exists to avoid).
        period_phrase = {"day": "day", "week": "week", "month": "month"}.get(
            profile.budget_period, profile.budget_period
        )
        usd_estimate = convert_to_usd(profile.budget_amount, profile.budget_currency)
        if usd_estimate is not None:
            bits.append(
                f"has a self-reported typical budget of about ${usd_estimate:.0f} USD per "
                f"{period_phrase} (converted from {profile.budget_amount} "
                f"{profile.budget_currency} using an approximate exchange rate - treat this as "
                "a rough estimate, not a precise constraint)"
            )
        else:
            # Defensive fallback only - budget_currency is a fixed choices
            # list that always matches users.currency's rate table, so
            # this shouldn't happen in practice, but degrade gracefully
            # rather than silently dropping the traveler's budget context.
            bits.append(
                f"has a self-reported typical budget around {profile.budget_amount} "
                f"{profile.budget_currency} per {period_phrase} (couldn't convert this "
                "currency to a common figure - treat as a rough personal reference point)"
            )
    if not bits:
        return ""
    return (
        "\n\nTraveler profile context (use only when relevant to this reply, don't force it "
        "in every time): " + "; ".join(bits) + "."
    )


def _entry_requirements_note(
    profile: TravelerProfile | None, destinations: list[Destination]
) -> str:
    """Real, verified visa-requirement facts for the traveler's own
    nationality against each candidate destination's country - built from
    travel.CountryEntryRequirement (2026-09-02, wiring in the table added
    earlier the same day but deliberately left unconnected until
    home_country existed anywhere to compare against). Deterministic
    lookup, not AI general knowledge, per 05_AI_DESIGN.md §7 - we only
    ever hand the model data our own dataset actually has, exactly like
    candidates_summary below. Only meaningful for real ScoredDestination
    candidates (a known .country); the no-matches/open-ended paths
    suggest destinations from the AI's own knowledge instead, so there's
    no reliable Destination row to look this up against there."""
    if profile is None or not profile.home_country:
        return ""
    lines = []
    seen_countries = set()
    for destination in destinations:
        country = destination.country
        if country in seen_countries:
            continue
        seen_countries.add(country)
        requirement = get_entry_requirements(country)
        if requirement is None:
            continue
        needs_visa = any(
            profile.home_country.strip().lower() == nationality.strip().lower()
            for nationality in requirement.visa_required_nationalities
        )
        visa_bit = (
            "a visa IS required"
            if needs_visa
            else "a visa is generally NOT required (see notes for exceptions/programs)"
        )
        lines.append(
            f"- {destination.name} ({country}): for a traveler from {profile.home_country}, "
            f"{visa_bit}. Notes: {requirement.visa_notes or 'none on file'}."
        )
    if not lines:
        return ""
    return (
        "\n\nEntry-requirement data on file for the traveler's own nationality (from our "
        "verified dataset, not general knowledge) - mention briefly ONLY if genuinely "
        "relevant to this reply, and if you do, always include this disclaimer: "
        f'"{ENTRY_REQUIREMENT_DISCLAIMER}"\n' + "\n".join(lines)
    )


def _extract_intent(
    message: str, *, ai_provider: AIProvider, history: list[dict] | None = None
) -> dict:
    messages = [AIMessage(role="system", content=INTENT_EXTRACTION_SYSTEM_PROMPT)]
    messages.extend(_history_messages(history))
    messages.append(AIMessage(role="user", content=message))
    # temperature=0: this call's output feeds directly into deterministic
    # application logic (which branch runs, what gets queried) - it needs
    # to be as consistent as possible given the same conversation, not
    # creative. Without this, the same message + history could extract
    # different fields (e.g. month) on different calls (a real bug found
    # live: an already-established value from one turn silently disappeared
    # on the very next, unprompted by anything the traveler said differently).
    data = ai_provider.generate_structured_reply(
        messages, json_schema=INTENT_SCHEMA, temperature=0
    )
    return _validate_intent(data)


def _validate_intent(data: dict) -> dict:
    # Response Validation (09_AI_ORCHESTRATION.md §9): never trust the
    # model's structured output blindly, even with a schema.
    if data.get("message_type") not in {"recommendation", "feedback", "future_intent", "off_topic"}:
        data["message_type"] = "recommendation"

    month = data.get("month")
    month_is_valid = isinstance(month, int) and 1 <= month <= 12
    data["month"] = month if month_is_valid else None
    data["month_was_assumed"] = False

    if data.get("message_type") == "recommendation" and not month_is_valid:
        # Month is the only thing RecommendationRequest needs to look up
        # real climate data, but a real user will rarely state every
        # dimension in one message - rather than blocking on it (removed
        # 2026-08-30, per direct user feedback: no field should ever gate
        # a real answer), always default to the current month and say so
        # transparently in the explanation, exactly like every other
        # unspecified field (trip_type, temperature, budget) already just
        # means "not relevant" rather than "missing".
        data["month"] = date.today().month
        data["month_was_assumed"] = True

    max_cost_of_living = data.get("max_cost_of_living")
    if max_cost_of_living is not None and not (1 <= max_cost_of_living <= MAX_COST_OF_LIVING_TIER):
        data["max_cost_of_living"] = None

    min_temp_c = data.get("min_temp_c")
    max_temp_c = data.get("max_temp_c")
    if min_temp_c is not None and max_temp_c is not None and min_temp_c > max_temp_c:
        # A contradictory extraction (e.g. "warm but not too hot" landing
        # min > max) - drop both rather than pass a range hard_constraints
        # in scoring.py would filter every destination out on.
        data["min_temp_c"] = None
        data["max_temp_c"] = None

    if data.get("trip_type") not in {*TRIP_TYPE_CODES, None}:
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


def _build_profile_confirmation_messages(
    message: str, profile: TravelerProfile, history: list[dict] | None = None
) -> list[AIMessage]:
    """Built once per conversation, the first time there's enough signal to
    actually suggest a destination and the traveler has relevant
    TravelerProfile details on file (2026-09-02, direct user request: "IA
    must always confirm this information with the user before suggest any
    destination"). Asks the traveler to confirm or correct the
    profile-derived context before anything gets suggested, rather than
    silently trusting stored preferences might not still apply to this
    trip. Only ever built once per conversation - see the
    memory.is_profile_confirmed gate in stream_travel_recommendation - the
    traveler's very next message proceeds straight to real suggestions no
    matter how they answered, matching the low-friction "never block a
    second time" philosophy the rest of this module already follows."""
    traveler_note = _traveler_context_note(profile)
    messages = [AIMessage(role="system", content=SYSTEM_PROMPT)]
    messages.extend(_history_messages(history))
    messages.append(
        AIMessage(
            role="user",
            content=(
                f'The traveler just said: "{message}" - this looks like enough to search for '
                "real destinations. Before suggesting anything, first briefly confirm the "
                "details already on file for this traveler still apply to this trip - ask "
                "naturally, in one short warm message, not a form or a checklist."
                f"{traveler_note}\n\n"
                "Mention only the details actually listed above - never invent or ask about "
                "one that isn't there. Do not suggest or list any destinations in this reply; "
                "that comes next, right after they confirm or correct these details. Reply in "
                "the same language the traveler has been using in this conversation (check the "
                "history above, not just this message) - this applies just as much to English "
                "as to any other language."
            ),
        )
    )
    return messages


def _build_explanation_messages(
    message: str,
    results: list[ScoredDestination],
    history: list[dict] | None = None,
    *,
    month_was_assumed: bool = False,
    month: int | None = None,
    profile: TravelerProfile | None = None,
    total_matches: int | None = None,
) -> list[AIMessage]:
    top_results = results[:MAX_RECOMMENDATIONS]
    candidates_summary = "\n".join(
        f"- {r.destination.name}, {r.destination.country}: avg high {r.avg_high_c}C, "
        f"cost tier {r.destination.cost_of_living}/5, trip type {r.destination.trip_type}"
        for r in top_results
    )
    assumed_month_note = (
        f"\n\nThe traveler didn't say what month, so we assumed month {month} "
        "(the current one) to be able to look up real climate data - mention "
        "this briefly and let them know they can give a different month if "
        "they have one in mind."
        if month_was_assumed
        else ""
    )
    traveler_note = _traveler_context_note(profile)
    entry_requirements_note = _entry_requirements_note(
        profile, [r.destination for r in top_results]
    )
    # 2026-09-02, direct user request: when the real match count exceeds
    # what we ever show (MAX_RECOMMENDATIONS), say so honestly rather than
    # silently presenting the capped list as if it were everything -
    # naming the actual number instead of a vague "there are more".
    more_matches_note = (
        f"\n\nThis request actually matched {total_matches} destinations in our data - "
        f"only the top {MAX_RECOMMENDATIONS} are listed above to keep this focused. "
        "Mention briefly that there are more options beyond these, and that narrowing "
        "the request further (dates, budget, a stronger preference) would help pick a "
        "better-tailored set rather than just a longer list."
        if total_matches is not None and total_matches > MAX_RECOMMENDATIONS
        else ""
    )

    messages = [AIMessage(role="system", content=SYSTEM_PROMPT)]
    messages.extend(_history_messages(history))
    messages.append(
        AIMessage(
            role="user",
            content=(
                f'The traveler asked: "{message}"\n\n'
                "Here are the top matching destinations, already filtered and "
                "ranked by the application. Do not invent any other destinations "
                "or facts beyond what is listed here:\n"
                f"{candidates_summary}"
                f"{assumed_month_note}"
                f"{traveler_note}"
                f"{entry_requirements_note}"
                f"{more_matches_note}\n\n"
                "Present the best 1-3 options as a compact Markdown table "
                "(standard pipe syntax) comparing them side by side - pick "
                "columns that actually matter here (e.g. destination, "
                "climate, cost, a standout pro, a real downside or "
                "trade-off to weigh) rather than a fixed template every "
                "time. A short sentence or two of context before or after "
                "the table is fine, but the comparison itself belongs in "
                "the table, not paragraphs of prose. After the table, "
                "don't just stop at the options - also ask one genuine "
                "follow-up question that would help narrow the search "
                "further (something not yet known: a preference, a "
                "priority between the options, anything relevant) the way "
                "a real consultant keeps refining even after giving a "
                "first real answer. Reply in the same language the "
                "traveler has been using in this conversation (check the "
                "history above, not just this message) - this applies "
                "just as much to English as to any other language."
            ),
        )
    )
    return messages


def _build_off_topic_messages(message: str, history: list[dict] | None = None) -> list[AIMessage]:
    """Built when the message isn't about travel at all. SYSTEM_PROMPT
    already tells the model how to handle this naturally - briefly and
    honestly engage with a reasonable question about the assistant itself,
    or warmly redirect (in its own words, never a fixed sentence) when the
    message is genuinely unrelated to both travel and the assistant. This
    just hands it the real message rather than returning a canned reply -
    2026-08-30, direct user feedback: always returning the identical
    sentence, even for something as mundane as "are you an AI?", was the
    clearest sign this "doesn't feel like an AI, just an if/else"."""
    messages = [AIMessage(role="system", content=SYSTEM_PROMPT)]
    messages.extend(_history_messages(history))
    messages.append(AIMessage(role="user", content=message))
    return messages


def _build_open_ended_messages(
    message: str,
    intent: dict,
    history: list[dict] | None = None,
    profile: TravelerProfile | None = None,
) -> list[AIMessage]:
    """Built when a recommendation-type message doesn't yet give enough to
    actually differentiate destinations by (see has_enough_signal in
    stream_travel_recommendation - a bare month or an exclusion alone
    still land here, not just a fully blank opener; trip_type alone no
    longer does as of 2026-09-02, now that it's real signal against a
    384-destination catalog).
    2026-08-30/31, direct user feedback: jumping straight to specific
    destination suggestions here felt presumptuous, and kept happening
    even with very little actually known - a real travel consultant
    naturally gathers more first instead of immediately listing
    destinations. 2026-08-31, further direct feedback ("ele precisa
    tentar pegar mais informações antes de tentar sugerir algo, quando o
    usuario pedir ajuda faz tipo um questionario bonitinho com emojis de
    praia, neve, viagem etc"): make that gathering step itself feel like a
    warm, quick little quiz with relevant emojis, not a plain sentence.
    This still shouldn't rigidly always ask, though - if the message
    already explicitly invites a guess (e.g. "surprise me", "you decide"),
    suggesting something is the more natural response. Both of these
    remain the AI's own judgment call, not a fixed rule encoded in Python.
    `intent` carries whatever weaker signal (month, trip_type, exclusions)
    was already extracted, so the model can acknowledge it and ask only
    about what's still missing instead of re-asking about it."""
    known_bits = []
    if intent["trip_type"]:
        known_bits.append(f"they want a {intent['trip_type']} trip")
    if intent["month"] and not intent["month_was_assumed"]:
        known_bits.append(f"they mentioned month {intent['month']}")
    if intent["excluded_place_names"]:
        known_bits.append(f"they want to avoid: {', '.join(intent['excluded_place_names'])}")
    known_note = (
        "\n\nYou already know this much from the conversation - don't ask "
        f"about it again, just build on it: {'; '.join(known_bits)}."
        if known_bits
        else ""
    )
    traveler_note = _traveler_context_note(profile)

    messages = [AIMessage(role="system", content=SYSTEM_PROMPT)]
    messages.extend(_history_messages(history))
    messages.append(
        AIMessage(
            role="user",
            content=(
                f'The traveler said: "{message}"\n\n'
                "You don't have enough yet to actually differentiate "
                "destinations - at minimum you're still missing climate/"
                f"temperature or budget preference.{known_note}{traveler_note}\n\n"
                "If this reads like an early point in the conversation "
                "(check the history - don't do this again if you already "
                "asked something like it recently), gather more with a "
                "short, warm, quiz-like message instead of a plain "
                "question: use relevant emojis for the main options you "
                "mention (e.g. beach, city, nature/adventure, culture, "
                "snow/mountain - adapt to what actually fits) and ask "
                "about trip type, rough timing/season, and budget "
                "together in one friendly message - do not re-ask about "
                "anything already known from the conversation. Do not "
                "list destinations yet in this case. If instead the "
                "message already explicitly invites you to just pick "
                "something (e.g. 'surprise me', 'you decide', 'anywhere "
                "is fine'), suggest 2-3 real destinations from your own "
                "general travel knowledge instead, confidently - present "
                "them as a compact Markdown table (standard pipe syntax) "
                "comparing them side by side rather than paragraphs of "
                "prose, and mention in passing that these come from your "
                "own knowledge rather than verified data, without opening "
                "with an apology or a caveat about not having data. Either "
                "way, write your "
                "reply in the same language the traveler has been using "
                "in this conversation (check the history above for this "
                "- judge it from the whole conversation, not just their "
                "latest short message) - this applies just as much to "
                "English as to any other language; do not default away "
                "from it."
            ),
        )
    )
    return messages


def _build_no_matches_messages(
    message: str,
    intent: dict,
    history: list[dict] | None = None,
    profile: TravelerProfile | None = None,
) -> list[AIMessage]:
    """Built when hard constraints eliminated every curated destination.

    Per the Phase 11 recommendation philosophy and direct user feedback
    (2026-08-30 - never just ask for more when a real answer is possible),
    this always tries to actually help rather than dead-ending or asking
    another question: reason from general travel knowledge instead, and
    treat whichever constraint made everything unmatchable as the one to
    relax, exactly like a hard filter our own scoring never even had to
    apply here would have been treated as a soft preference."""
    constraints = []
    if intent["month"]:
        constraints.append(f"month={intent['month']}")
    if intent["trip_type"]:
        constraints.append(f"trip_type={intent['trip_type']}")
    if intent["min_temp_c"] is not None:
        constraints.append(f"min_temp_c={intent['min_temp_c']}")
    if intent["max_temp_c"] is not None:
        constraints.append(f"max_temp_c={intent['max_temp_c']}")
    if intent["max_cost_of_living"] is not None:
        constraints.append(f"max_cost_of_living={intent['max_cost_of_living']}/{MAX_COST_OF_LIVING_TIER}")
    if intent["excluded_place_names"]:
        constraints.append(f"excluded={', '.join(intent['excluded_place_names'])}")
    constraints_summary = ", ".join(constraints) if constraints else "no specific constraints"
    traveler_note = _traveler_context_note(profile)

    messages = [AIMessage(role="system", content=SYSTEM_PROMPT)]
    messages.extend(_history_messages(history))
    messages.append(
        AIMessage(
            role="user",
            content=(
                f'The traveler asked: "{message}"\n\n'
                "Our own curated destination data has no match for this "
                f"({constraints_summary}) - taken together, these "
                "constraints are too narrow for what we have on file."
                f"{traveler_note}\n\n"
                "Suggest 1-3 real destinations from your own general "
                "travel knowledge that fit the traveler's request as well "
                "as possible, relaxing whichever constraint seems least "
                "essential to what they actually care about (never ask "
                "them to do this for you). Present them as a compact "
                "Markdown table (standard pipe syntax) comparing them "
                "side by side - pick columns that actually matter here "
                "(e.g. destination, climate, cost, a standout pro, a real "
                "downside or trade-off) rather than paragraphs of prose. "
                "Lead with real, confident help - do NOT open by saying "
                "you don't have data or apologizing for lacking specific "
                "information (never start with something like "
                "'unfortunately I don't have data for this'); a real "
                "travel consultant asked about something outside their "
                "usual reference material just helps, the same way. "
                "Mention that these particular suggestions come from your "
                "own knowledge rather than our verified dataset briefly "
                "and in passing - so the traveler knows to double-check "
                "current details - not as an apology or a caveat that "
                "opens the reply. After the table, also ask one genuine "
                "follow-up question that would help narrow the search "
                "further, the way a real consultant keeps refining even "
                "after giving a first real answer. Only ask a clarifying "
                "question INSTEAD of suggesting if the message truly gives "
                "you nothing at all to go on (not even a vibe, place "
                "type, or timing) - this should be rare. Reply in the "
                "same language the traveler has been using in this "
                "conversation (check the history above, not just this "
                "message) - this applies just as much to English as to "
                "any other language."
            ),
        )
    )
    return messages


def _build_unrecognized_future_destination_messages(
    message: str, destination_name: str, history: list[dict] | None = None
) -> list[AIMessage]:
    """Built when a future_intent message names a real destination our
    curated catalog doesn't have (2026-09-02, direct user feedback: a
    canned "I don't have it, but I've noted it" reply was unhelpful and
    contradicted the Phase 11 recommendation philosophy - the AI should
    reason from its own general knowledge here too, the same way an
    unmatched recommendation request already does). No Trip is persisted
    for this - Trip.destination is a real FK, and there is no valid
    Destination row to attach it to (never invent catalog data,
    05_AI_DESIGN.md §7) - the reply says so honestly in passing, without
    dwelling on it as an apology."""
    messages = [AIMessage(role="system", content=SYSTEM_PROMPT)]
    messages.extend(_history_messages(history))
    messages.append(
        AIMessage(
            role="user",
            content=(
                f'The traveler just said: "{message}" - naming {destination_name} as '
                "somewhere they'd like to go someday. This destination isn't in our "
                "curated dataset, so it can't be formally tracked as a saved future trip "
                "the way a catalog destination would be. Respond warmly and helpfully "
                "using your own general travel knowledge about it - share a genuine, "
                "useful detail or two (what it's known for, a good time to visit, "
                "something practical) the way a knowledgeable travel consultant would, "
                "rather than just acknowledging the message. Mention in passing, without "
                "opening with an apology, that you can't formally save it as a tracked "
                "trip yet since it's outside your verified catalog - but you're glad to "
                "help them think it through. Reply in the same language the traveler has "
                "been using in this conversation (check the history above, not just this "
                "message) - this applies just as much to English as to any other "
                "language."
            ),
        )
    )
    return messages


def _build_unrecognized_feedback_destination_messages(
    message: str, destination_name: str, history: list[dict] | None = None
) -> list[AIMessage]:
    """Built when a feedback message is about a real destination our
    curated catalog doesn't have (2026-09-02 review - the same "use AI
    general knowledge instead of a canned dead-end" fix already applied
    to future_intent, for the identical underlying situation). No
    TravelHistoryEntry/Feedback row is persisted for this -
    TravelHistoryEntry.destination is a real FK, and there is no valid
    Destination row to attach it to (never invent catalog data,
    05_AI_DESIGN.md §7) - the reply says so honestly in passing, without
    dwelling on it as an apology."""
    messages = [AIMessage(role="system", content=SYSTEM_PROMPT)]
    messages.extend(_history_messages(history))
    messages.append(
        AIMessage(
            role="user",
            content=(
                f'The traveler just said: "{message}" - sharing their own experience of '
                f"{destination_name}, a place they've visited. This destination isn't in "
                "our curated dataset, so their visit can't be formally recorded in their "
                "travel history the way a catalog destination would be. Respond warmly - "
                "genuinely engage with what they shared (using your own general travel "
                "knowledge about the place to react to it naturally, the way a real "
                "travel consultant who knows the destination would), rather than just "
                "acknowledging the message. Mention in passing, without opening with an "
                "apology, that you can't formally log it in their travel history yet "
                "since it's outside your verified catalog - but thank them for sharing. "
                "Reply in the same language the traveler has been using in this "
                "conversation (check the history above, not just this message) - this "
                "applies just as much to English as to any other language."
            ),
        )
    )
    return messages
