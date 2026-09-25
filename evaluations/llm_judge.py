"""Optional LLM-as-judge (§10): scores subjective qualities a structural
check can't reach - usefulness, clarity, whether the reply addresses the
traveler's actual stated preferences, whether it communicates real
trade-offs. Only ever supplements the deterministic checks in
evaluations.invariants/evaluations.grounding, never replaces them, and
production ranking never reads this output - it exists purely for the
human-facing evaluation report. Only runs with --with-llm-judge (real
AI cost per scenario judged).
"""

from __future__ import annotations

from dataclasses import dataclass

from ai.provider import AIMessage, AIProvider, AIProviderError

# Bumped whenever the prompt/schema meaningfully changes, so a run
# artifact's judge scores stay interpretable against the prompt version
# that actually produced them (§10's "store evaluator prompt/version/
# model metadata").
JUDGE_PROMPT_VERSION = "v1"

JUDGE_SYSTEM_PROMPT = (
    "You are grading a travel-recommendation assistant's reply for QUALITY, not "
    "factual correctness - a separate deterministic system already checks facts "
    "against real destination data. Given the traveler's message and the "
    "assistant's reply, rate: usefulness (1-5, does this genuinely help the "
    "traveler decide), clarity (1-5, is it well-organized and easy to follow), "
    "whether it addresses the SPECIFIC preferences the traveler actually stated "
    "(not generic travel advice that would apply to anyone), and whether it "
    "communicates real trade-offs between the options rather than just listing "
    "them side by side. Be a strict, consistent grader - a 3 should mean "
    "genuinely average, not a diplomatic middle score."
)

JUDGE_SCHEMA = {
    "name": "explanation_quality_judgment",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "usefulness": {"type": "integer"},
            "clarity": {"type": "integer"},
            "addresses_stated_preferences": {"type": "boolean"},
            "communicates_tradeoffs": {"type": "boolean"},
            "rationale": {"type": "string"},
        },
        "required": [
            "usefulness",
            "clarity",
            "addresses_stated_preferences",
            "communicates_tradeoffs",
            "rationale",
        ],
        "additionalProperties": False,
    },
}


@dataclass(frozen=True)
class JudgeResult:
    scenario_id: str
    model: str
    prompt_version: str
    usefulness: int
    clarity: int
    addresses_stated_preferences: bool
    communicates_tradeoffs: bool
    rationale: str

    def to_json(self) -> dict:
        return {
            "scenario_id": self.scenario_id,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "usefulness": self.usefulness,
            "clarity": self.clarity,
            "addresses_stated_preferences": self.addresses_stated_preferences,
            "communicates_tradeoffs": self.communicates_tradeoffs,
            "rationale": self.rationale,
        }


def judge_explanation(
    scenario_id: str,
    scenario_message: str,
    reply: str,
    *,
    ai_provider: AIProvider,
    model_name: str,
) -> JudgeResult | None:
    """Never trusts the judge's structured output blindly, same
    discipline as every other structured AI call in this codebase - a
    failed call or a malformed response just yields None, which the
    runner treats as "not judged" rather than crashing the whole run."""
    try:
        response = ai_provider.generate_structured_reply(
            [
                AIMessage(role="system", content=JUDGE_SYSTEM_PROMPT),
                AIMessage(
                    role="user",
                    content=(
                        f"Traveler's message: {scenario_message!r}\n\nAssistant's reply: {reply!r}"
                    ),
                ),
            ],
            json_schema=JUDGE_SCHEMA,
        )
    except AIProviderError:
        return None
    if not isinstance(response, dict):
        return None
    try:
        return JudgeResult(
            scenario_id=scenario_id,
            model=model_name,
            prompt_version=JUDGE_PROMPT_VERSION,
            usefulness=int(response["usefulness"]),
            clarity=int(response["clarity"]),
            addresses_stated_preferences=bool(response["addresses_stated_preferences"]),
            communicates_tradeoffs=bool(response["communicates_tradeoffs"]),
            rationale=str(response["rationale"]),
        )
    except (KeyError, TypeError, ValueError):
        return None
