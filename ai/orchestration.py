from collections.abc import Iterator
from dataclasses import dataclass

from recommendations.scoring import (
    RecommendationRequest,
    ScoredDestination,
    generate_recommendations,
)
from travel.services import find_destination_slugs_by_name

from .prompts import SYSTEM_PROMPT
from .provider import AIMessage, AIProvider, AIProviderError, get_ai_provider

MAX_EXPLAINED_CANDIDATES = 5

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

INTENT_EXTRACTION_SYSTEM_PROMPT = (
    "You extract structured travel search constraints from a traveler's message. "
    "Set is_travel_request to false if the message is not about travel planning. "
    "Set needs_clarification to true, with a short clarification_question, if the "
    "message is a travel request but is missing information you would need - at "
    "minimum, a target month. Never guess a month the user did not state or "
    "clearly imply.\n\n"
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
    "because they used words instead of a number.\n\n"
    "For trip_type, only set it when the message clearly matches one of "
    "exactly these four categories: 'beach' (beach/coastal holiday), "
    "'city' (city break/urban trip), 'nature' (outdoors/adventure/hiking), "
    "'culture' (history/museums/cultural immersion). Leave it null if the "
    "request doesn't clearly match one of these four, or matches more than "
    "one - do not force-fit a vibe like 'romantic' or 'family-friendly' "
    "into one of these categories just because you have to pick something.\n\n"
    "If the user asks to avoid or exclude specific places, countries, or "
    "regions, list the place/country names they mentioned in "
    "excluded_place_names (e.g. ['Marrakech', 'Morocco']). Leave it as an "
    "empty list if they mentioned no exclusions."
)

INTENT_SCHEMA = {
    "name": "travel_intent",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "is_travel_request": {"type": "boolean"},
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
        },
        "required": [
            "is_travel_request",
            "needs_clarification",
            "clarification_question",
            "month",
            "min_temp_c",
            "max_cost_of_living",
            "trip_type",
            "excluded_place_names",
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
    ai_provider: AIProvider | None = None,
    climate_provider=None,
) -> StreamingOrchestrationResult:
    """Turn one natural-language travel message into a grounded, explained
    recommendation, streaming the explanation incrementally.

    Pipeline (09_AI_ORCHESTRATION.md §3): Intent Understanding -> Travel Data
    + Rules & Constraints -> Recommendation Scoring -> AI Reasoning (streamed).
    This is the core orchestration logic; get_travel_recommendation() is a
    non-streaming convenience wrapper around it. Does NOT handle conversation
    history/persistence - each call is independent (Phase 10's chat UI keeps
    per-visit display only, not true multi-turn context yet).
    """
    ai_provider = ai_provider or get_ai_provider()

    try:
        intent = _extract_intent(message, ai_provider=ai_provider)
    except AIProviderError:
        return StreamingOrchestrationResult(False, [], iter([FALLBACK_REPLY]))

    if not intent["is_travel_request"]:
        return StreamingOrchestrationResult(False, [], iter([OFF_TOPIC_REPLY]))

    if intent["needs_clarification"]:
        question = intent["clarification_question"] or "Could you tell me more about your trip?"
        return StreamingOrchestrationResult(True, [], iter([question]))

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
        return StreamingOrchestrationResult(False, [], iter([NO_MATCHES_REPLY]))

    messages = _build_explanation_messages(message, results)

    def _stream_explanation():
        try:
            yield from ai_provider.stream_reply(messages)
        except AIProviderError:
            # A partial reply may already have been yielded before a
            # mid-stream failure (09_AI_ORCHESTRATION.md §12: "Interrupted
            # streams" must be handled) - appending the fallback message is
            # an acceptable degrade rather than losing the request entirely.
            yield FALLBACK_REPLY

    return StreamingOrchestrationResult(False, results, _stream_explanation())


def get_travel_recommendation(
    message: str,
    *,
    user=None,
    ai_provider: AIProvider | None = None,
    climate_provider=None,
) -> OrchestrationResult:
    """Non-streaming convenience wrapper around stream_travel_recommendation() -
    joins all chunks into one string. Useful for tests and any caller that
    doesn't need incremental output.
    """
    streaming_result = stream_travel_recommendation(
        message, user=user, ai_provider=ai_provider, climate_provider=climate_provider
    )
    reply = "".join(streaming_result.reply_chunks)
    return OrchestrationResult(
        reply, streaming_result.needs_clarification, streaming_result.recommendations
    )


def _extract_intent(message: str, *, ai_provider: AIProvider) -> dict:
    messages = [
        AIMessage(role="system", content=INTENT_EXTRACTION_SYSTEM_PROMPT),
        AIMessage(role="user", content=message),
    ]
    data = ai_provider.generate_structured_reply(messages, json_schema=INTENT_SCHEMA)
    return _validate_intent(data)


def _validate_intent(data: dict) -> dict:
    # Response Validation (09_AI_ORCHESTRATION.md §9): never trust the
    # model's structured output blindly, even with a schema.
    month = data.get("month")
    if not isinstance(month, int) or not (1 <= month <= 12):
        data["month"] = None
        if data.get("is_travel_request") and not data.get("needs_clarification"):
            data["needs_clarification"] = True
            data["clarification_question"] = (
                data.get("clarification_question") or "Which month are you thinking of traveling?"
            )

    max_cost_of_living = data.get("max_cost_of_living")
    if max_cost_of_living is not None and not (1 <= max_cost_of_living <= 5):
        data["max_cost_of_living"] = None

    if data.get("trip_type") not in {"beach", "city", "nature", "culture", None}:
        data["trip_type"] = None

    excluded_place_names = data.get("excluded_place_names")
    if not isinstance(excluded_place_names, list):
        data["excluded_place_names"] = []
    else:
        data["excluded_place_names"] = [
            name for name in excluded_place_names if isinstance(name, str) and name.strip()
        ]

    return data


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
