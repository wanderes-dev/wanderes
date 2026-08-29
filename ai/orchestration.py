from dataclasses import dataclass

from recommendations.scoring import (
    RecommendationRequest,
    ScoredDestination,
    generate_recommendations,
)

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
    "Only leave a field null when the user gave no indication at all for that "
    "dimension - do not leave it null just because they used words instead "
    "of a number."
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
        },
        "required": [
            "is_travel_request",
            "needs_clarification",
            "clarification_question",
            "month",
            "min_temp_c",
            "max_cost_of_living",
        ],
        "additionalProperties": False,
    },
}


@dataclass(frozen=True)
class OrchestrationResult:
    reply: str
    needs_clarification: bool
    recommendations: list[ScoredDestination]


def get_travel_recommendation(
    message: str,
    *,
    user=None,
    ai_provider: AIProvider | None = None,
    climate_provider=None,
) -> OrchestrationResult:
    """Turn one natural-language travel message into a grounded, explained recommendation.

    Pipeline (09_AI_ORCHESTRATION.md §3): Intent Understanding -> Travel Data
    + Rules & Constraints -> Recommendation Scoring -> AI Reasoning. Does
    NOT handle conversation history/persistence or streaming - those need
    the chat interface (Phase 10) to exist first; this is a stateless,
    single-message orchestrator.
    """
    ai_provider = ai_provider or get_ai_provider()

    try:
        intent = _extract_intent(message, ai_provider=ai_provider)

        if not intent["is_travel_request"]:
            return OrchestrationResult(
                OFF_TOPIC_REPLY, needs_clarification=False, recommendations=[]
            )

        if intent["needs_clarification"]:
            question = intent["clarification_question"] or "Could you tell me more about your trip?"
            return OrchestrationResult(question, needs_clarification=True, recommendations=[])

        request = RecommendationRequest(
            month=intent["month"],
            min_temp_c=intent["min_temp_c"],
            max_cost_of_living=intent["max_cost_of_living"],
            user=user,
        )
        results = generate_recommendations(request, climate_provider=climate_provider)

        if not results:
            return OrchestrationResult(
                NO_MATCHES_REPLY, needs_clarification=False, recommendations=[]
            )

        reply = _explain_results(message, results, ai_provider=ai_provider)
        return OrchestrationResult(reply, needs_clarification=False, recommendations=results)
    except AIProviderError:
        # Failures should produce a useful response without exposing
        # internal details (09_AI_ORCHESTRATION.md §12). Deliberately
        # simple: any AI failure anywhere in the pipeline falls back to the
        # same generic reply, rather than trying to salvage partial work.
        return OrchestrationResult(FALLBACK_REPLY, needs_clarification=False, recommendations=[])


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

    return data


def _explain_results(
    message: str, results: list[ScoredDestination], *, ai_provider: AIProvider
) -> str:
    top_results = results[:MAX_EXPLAINED_CANDIDATES]
    candidates_summary = "\n".join(
        f"- {r.destination.name}, {r.destination.country}: avg high {r.avg_high_c}C, "
        f"cost tier {r.destination.cost_of_living}/5, trip type {r.destination.trip_type}"
        for r in top_results
    )

    messages = [
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
    response = ai_provider.generate_reply(messages)
    return response.content
