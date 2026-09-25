"""Runs the evaluation corpus and produces one ScenarioResult per
scenario. Two fundamentally different execution paths, chosen per
scenario by whether the caller asked for deterministic-only mode:

- Deterministic-only: builds a RecommendationRequest directly from the
  scenario's own `deterministic_request` ground truth and calls
  recommendations.scoring.generate_recommendations - zero AI calls, zero
  cost, exercises only the scoring/ranking layer. Every scenario
  supports this (scenarios with no `deterministic_request` just get an
  empty invariant set - "not applicable" - rather than being skipped).
- Full pipeline: calls the real
  ai.orchestration.stream_travel_recommendation() entry point with a
  real AIProvider, so intent extraction, branching, scoring, and
  explanation generation all run exactly as they do for a live
  traveler. Costs real AI calls (see evaluations.cost).
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field, replace

from ai.orchestration import stream_travel_recommendation
from ai.provider import AIProvider, AIProviderError, get_ai_provider
from integrations.climate import get_climate_provider
from recommendations.scoring import ScoredDestination

from .cost import CostTracker
from .grounding import GroundingResult, run_grounding_checks
from .intent_eval import IntentEvalResult, evaluate_intent
from .invariants import (
    InvariantResult,
    check_ranking_deterministic_for_identical_input,
    run_scenario_invariants,
)
from .llm_judge import JudgeResult, judge_explanation
from .profiles import synthetic_traveler
from .requests import build_request
from .scenarios import Scenario
from .trace import RecommendationTrace, trace_recommendations


# The real pipeline's own branch priority (ai.orchestration.stream_travel_recommendation,
# checked in this exact order) - used to infer, from the extracted
# intent alone, which flow SHOULD have fired, independent of what
# StreamingOrchestrationResult happens to expose for that branch. Kept
# here rather than imported, since orchestration exposes no such mapping
# itself (it's implicit in the if/elif chain) - this is this module's
# own understanding of that order, verified against orchestration.py
# during development and worth re-checking if that chain is ever
# reordered.
def _checked_scenario_for_full_pipeline(scenario: Scenario, intent: dict) -> Scenario:
    """Hard-constraint invariants (budget/temperature/trip_type/country)
    must be checked against what the pipeline actually extracted, not
    against the scenario's own declared deterministic_request - that
    ground truth represents what extraction SHOULD have produced, and
    using it directly would blame the scoring layer for an extraction
    miss that evaluations.intent_eval already measures independently
    (confirmed empirically: the baseline's first real run flagged
    temperature_bounds_respected as "violated" for a scenario where the
    model correctly extracted no temperature constraint at all - scoring
    behaved perfectly given what it was told).

    Exclusion is the deliberate exception: must_not_include_slugs stays
    checked against the scenario's own declaration (unchanged, not
    touched here) - "never recommend what the traveler explicitly said
    to avoid" is an end-to-end product promise worth checking regardless
    of which layer would be at fault for missing it, and a failure there
    is still correctly attributable via intent_eval's own
    excluded_place_names comparison when the root cause is extraction."""
    base = scenario.deterministic_request or {}
    derived_request = {
        "month": intent.get("month") or base.get("month") or 6,
        "min_temp_c": intent.get("min_temp_c"),
        "max_temp_c": intent.get("max_temp_c"),
        "max_cost_of_living": intent.get("max_cost_of_living"),
        "trip_type": intent.get("trip_type"),
        "continent": intent.get("continent"),
        "country": intent.get("country"),
        "excluded_slugs": base.get("excluded_slugs", []),
    }
    return replace(scenario, deterministic_request=derived_request)


def _infer_expected_flow(intent: dict) -> str:
    if intent.get("is_recall_request"):
        return "recall"
    if intent.get("is_visa_or_entry_question"):
        return "visa"
    if intent.get("is_booking_request"):
        return "booking"
    if intent.get("is_accommodation_request"):
        return "accommodation"
    if intent.get("is_video_request"):
        return "video"
    if intent.get("is_activity_question"):
        return "activity"
    message_type = intent.get("message_type")
    if message_type in ("off_topic", "feedback", "future_intent"):
        return message_type
    return "recommendation"


@dataclass
class ScenarioResult:
    scenario: Scenario
    mode: str  # "deterministic" | "full"
    flow_matched: bool
    reply: str
    scored: list[ScoredDestination] = field(default_factory=list)
    invariants: list[InvariantResult] = field(default_factory=list)
    intent_eval: IntentEvalResult | None = None
    grounding: list[GroundingResult] = field(default_factory=list)
    judge: JudgeResult | None = None
    trace: RecommendationTrace | None = None
    error: str | None = None
    latency_ms: float = 0.0

    @property
    def scored_slugs(self) -> list[str]:
        return [s.destination.slug for s in self.scored]

    @property
    def passed(self) -> bool:
        if self.error is not None:
            return False
        if not self.flow_matched:
            return False
        if self.intent_eval is not None and not self.intent_eval.all_match:
            return False
        if not all(r.passed for r in self.invariants):
            return False
        if not all(r.passed for r in self.grounding):
            return False
        return True

    def failed_check_names(self) -> list[str]:
        names = []
        if self.error is not None:
            names.append("error")
        if not self.flow_matched:
            names.append("flow_mismatch")
        if self.intent_eval is not None:
            names += [
                f"intent_field:{c.field}" for c in self.intent_eval.comparisons if not c.matches
            ]
        names += [r.name for r in self.invariants if not r.passed]
        names += [r.name for r in self.grounding if not r.passed]
        return names

    def to_json(self) -> dict:
        return {
            "id": self.scenario.id,
            "split": self.scenario.split,
            "category": self.scenario.category,
            "mode": self.mode,
            "passed": self.passed,
            "flow_matched": self.flow_matched,
            "expected_flow": self.scenario.expected_flow,
            "reply": self.reply,
            "scored_slugs": self.scored_slugs,
            "invariants": [
                {"name": r.name, "passed": r.passed, "detail": r.detail} for r in self.invariants
            ],
            "intent_eval": self.intent_eval.to_json() if self.intent_eval else None,
            "grounding": [
                {"name": r.name, "passed": r.passed, "detail": r.detail} for r in self.grounding
            ],
            "judge": self.judge.to_json() if self.judge else None,
            "trace": self.trace.to_json() if self.trace else None,
            "error": self.error,
            "latency_ms": self.latency_ms,
            "failed_checks": self.failed_check_names(),
        }


def _run_deterministic(scenario: Scenario, *, climate_provider) -> ScenarioResult:
    if scenario.deterministic_request is None:
        scored: list[ScoredDestination] = []
        trace = None
        invariants = run_scenario_invariants(scenario, scored)
    else:
        # preference_fit/repetition_penalty only ever apply to a real
        # authenticated user (recommendations.scoring._preferred_trip_types/
        # _visited_destination_slugs both return empty for user=None) - a
        # scenario testing either one needs the same throwaway synthetic
        # traveler the full-pipeline path uses, even though this path
        # never touches the AI at all.
        with synthetic_traveler(scenario.id, scenario.profile_overrides) as user:
            request = build_request(scenario.deterministic_request, user=user)
            scored, trace = trace_recommendations(request, climate_provider=climate_provider)
            invariants = run_scenario_invariants(scenario, scored)
            # Re-runs scoring once more with the identical request - cheap
            # in practice since integrations.climate caches (7-day TTL),
            # so this second pass is normally a cache hit, not a second
            # round of network calls. Skipped when the first pass hit its
            # own time budget: recommendations.scoring's
            # CLIMATE_LOOKUP_TIME_BUDGET_SECONDS is a real wall-clock
            # race by design (a deliberate production safety valve, not a
            # hidden-randomness bug) - a second, freshly-timed pass can
            # legitimately reach further into an unordered, only
            # partially-cached candidate queryset than the first one did,
            # which would flag this check red for a reason that has
            # nothing to do with whether ranking itself is deterministic.
            # Confirmed empirically: every scenario that failed this
            # check in the first real run was one that had also hit the
            # time budget.
            if not trace.time_budget_exceeded:
                invariants.append(
                    check_ranking_deterministic_for_identical_input(
                        request, climate_provider=climate_provider
                    )
                )
    return ScenarioResult(
        scenario=scenario,
        mode="deterministic",
        flow_matched=True,  # not applicable - no message routing happened
        reply="",
        scored=scored,
        invariants=invariants,
        trace=trace,
    )


def _run_full_pipeline(
    scenario: Scenario,
    *,
    ai_provider: AIProvider,
    climate_provider,
    cost: CostTracker,
    with_llm_judge: bool,
) -> ScenarioResult:
    started_at = time.perf_counter()
    with synthetic_traveler(scenario.id, scenario.profile_overrides) as user:
        intent_sink: dict = {}
        try:
            result = stream_travel_recommendation(
                scenario.message,
                user=user,
                session_key=None if user else f"eval-{scenario.id}",
                ai_provider=ai_provider,
                climate_provider=climate_provider,
                history_override=list(scenario.history) or None,
                intent_sink=intent_sink,
            )
            reply = "".join(result.reply_chunks)
        except AIProviderError as exc:
            latency_ms = (time.perf_counter() - started_at) * 1000
            return ScenarioResult(
                scenario=scenario,
                mode="full",
                flow_matched=False,
                reply="",
                error=str(exc),
                latency_ms=latency_ms,
            )
    latency_ms = (time.perf_counter() - started_at) * 1000
    cost.record_pipeline_call(scenario_message=scenario.message, reply=reply)

    inferred_flow = _infer_expected_flow(intent_sink) if intent_sink else scenario.expected_flow
    if inferred_flow == "accommodation" and result.accommodation_freeform_name:
        inferred_flow = "accommodation_freeform"
    flow_matched = inferred_flow == scenario.expected_flow

    scored = list(result.recommendations)
    checked_scenario = _checked_scenario_for_full_pipeline(scenario, intent_sink)
    invariants = run_scenario_invariants(checked_scenario, scored)
    grounding = run_grounding_checks(reply, scored)
    intent_eval = evaluate_intent(scenario, intent_sink) if scenario.expected_intent else None

    judge = None
    if with_llm_judge and reply:
        judge = judge_explanation(
            scenario.id,
            scenario.message,
            reply,
            ai_provider=ai_provider,
            model_name=cost.model_name,
        )
        if judge is not None:
            cost.record_judge_call(scenario_message=scenario.message, reply=reply)

    return ScenarioResult(
        scenario=scenario,
        mode="full",
        flow_matched=flow_matched,
        reply=reply,
        scored=scored,
        invariants=invariants,
        intent_eval=intent_eval,
        grounding=grounding,
        judge=judge,
        latency_ms=latency_ms,
    )


def select_scenarios(
    scenarios: list[Scenario], *, split: str | None, sample: int | None, seed: int = 1337
) -> list[Scenario]:
    pool = [s for s in scenarios if split is None or s.split == split]
    if sample is None or sample >= len(pool):
        return pool
    rng = random.Random(seed)
    return rng.sample(pool, sample)


def run_scenarios(
    scenarios: list[Scenario],
    *,
    deterministic_only: bool,
    with_llm_judge: bool = False,
    ai_provider: AIProvider | None = None,
    climate_provider=None,
) -> tuple[list[ScenarioResult], CostTracker]:
    climate_provider = climate_provider or get_climate_provider()
    # AIProvider implementations (e.g. OpenAIProvider) don't expose the
    # configured model name as a public attribute - settings.AI_MODEL is
    # the one reliable source, same value the provider itself reads.
    from django.conf import settings

    cost = CostTracker(model_name=getattr(settings, "AI_MODEL", "unknown"))
    results = []

    if deterministic_only:
        for scenario in scenarios:
            results.append(_run_deterministic(scenario, climate_provider=climate_provider))
        return results, cost

    ai_provider = ai_provider or get_ai_provider()
    for scenario in scenarios:
        results.append(
            _run_full_pipeline(
                scenario,
                ai_provider=ai_provider,
                climate_provider=climate_provider,
                cost=cost,
                with_llm_judge=with_llm_judge,
            )
        )
    return results, cost
