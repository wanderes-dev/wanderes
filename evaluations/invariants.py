"""Deterministic, machine-verifiable invariants: things that should
objectively never happen, independent of which destination "should" win
a given scenario (that's a matter of judgment - these aren't). Every
check here is a pure function over already-computed data, no AI calls,
no network access - safe to run in --deterministic-only mode.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass

from recommendations.scoring import (
    RecommendationRequest,
    ScoredDestination,
    generate_recommendations,
)

from .scenarios import Scenario


@dataclass(frozen=True)
class InvariantResult:
    name: str
    passed: bool
    detail: str = ""


def check_excluded_destinations_absent(
    scenario: Scenario, scored: list[ScoredDestination]
) -> InvariantResult:
    excluded = set((scenario.deterministic_request or {}).get("excluded_slugs") or ())
    if not excluded:
        return InvariantResult("excluded_destinations_absent", True, "no exclusions declared")
    present = excluded & {s.destination.slug for s in scored}
    return InvariantResult(
        "excluded_destinations_absent",
        not present,
        f"excluded but present: {sorted(present)}" if present else "clean",
    )


def check_must_not_include_absent(
    scenario: Scenario, scored: list[ScoredDestination]
) -> InvariantResult:
    if not scenario.must_not_include_slugs:
        return InvariantResult("must_not_include_absent", True, "none declared")
    forbidden = set(scenario.must_not_include_slugs)
    present = forbidden & {s.destination.slug for s in scored}
    return InvariantResult(
        "must_not_include_absent",
        not present,
        f"objectively-wrong destination(s) present: {sorted(present)}" if present else "clean",
    )


def check_hard_budget_respected(
    scenario: Scenario, scored: list[ScoredDestination]
) -> InvariantResult:
    max_cost = (scenario.deterministic_request or {}).get("max_cost_of_living")
    if max_cost is None:
        return InvariantResult("hard_budget_respected", True, "no budget ceiling declared")
    violators = [s.destination.slug for s in scored if s.destination.cost_of_living > max_cost]
    return InvariantResult(
        "hard_budget_respected",
        not violators,
        f"over cost ceiling {max_cost}: {violators}" if violators else "clean",
    )


def check_temperature_bounds_respected(
    scenario: Scenario, scored: list[ScoredDestination]
) -> InvariantResult:
    req = scenario.deterministic_request or {}
    min_temp, max_temp = req.get("min_temp_c"), req.get("max_temp_c")
    if min_temp is None and max_temp is None:
        return InvariantResult(
            "temperature_bounds_respected", True, "no temperature bound declared"
        )
    violators = []
    for s in scored:
        if s.avg_high_c is None:
            continue
        if min_temp is not None and s.avg_high_c < min_temp:
            violators.append(s.destination.slug)
        elif max_temp is not None and s.avg_high_c > max_temp:
            violators.append(s.destination.slug)
    return InvariantResult(
        "temperature_bounds_respected",
        not violators,
        f"outside [{min_temp}, {max_temp}]: {violators}" if violators else "clean",
    )


def check_trip_type_respected(
    scenario: Scenario, scored: list[ScoredDestination]
) -> InvariantResult:
    trip_type = (scenario.deterministic_request or {}).get("trip_type")
    if trip_type is None:
        return InvariantResult("trip_type_respected", True, "no trip_type constraint declared")
    violators = [s.destination.slug for s in scored if s.destination.trip_type != trip_type]
    return InvariantResult(
        "trip_type_respected",
        not violators,
        f"wrong trip_type present: {violators}" if violators else "clean",
    )


def check_ranking_sorted_descending(scored: list[ScoredDestination]) -> InvariantResult:
    scores = [s.score for s in scored]
    is_sorted = all(scores[i] >= scores[i + 1] for i in range(len(scores) - 1))
    return InvariantResult(
        "ranking_sorted_descending", is_sorted, "clean" if is_sorted else f"out of order: {scores}"
    )


def check_ranking_deterministic_for_identical_input(
    request: RecommendationRequest, *, climate_provider
) -> InvariantResult:
    """Runs the exact same request twice and asserts an identical ranked
    slug order - the "no hidden randomness" invariant. Costs one extra
    scoring pass; only called from the runner, not from every scenario's
    default check set, since most scenarios don't need it repeated."""
    first = generate_recommendations(request, climate_provider=climate_provider)
    second = generate_recommendations(request, climate_provider=climate_provider)
    first_order = [s.destination.slug for s in first]
    second_order = [s.destination.slug for s in second]
    matches = first_order == second_order
    return InvariantResult(
        "ranking_deterministic_for_identical_input",
        matches,
        "clean" if matches else f"{first_order} != {second_order}",
    )


def check_acceptable_slugs_if_declared(
    scenario: Scenario, scored: list[ScoredDestination]
) -> InvariantResult:
    """Soft-ish but still machine-verifiable: when a scenario declares a
    whitelist of destinations that would genuinely satisfy the traveler
    (straightforward cases only - see scenarios.py's docstring on why
    most scenarios leave this unset), the top-ranked destination should
    be a member. Not checked at all when unset - multiple defensible
    answers is the norm, not the exception, per the corpus design."""
    if scenario.acceptable_slugs is None:
        return InvariantResult("winner_in_acceptable_set", True, "no whitelist declared")
    if not scored:
        return InvariantResult("winner_in_acceptable_set", False, "no destination was recommended")
    winner = scored[0].destination.slug
    ok = winner in scenario.acceptable_slugs
    return InvariantResult(
        "winner_in_acceptable_set",
        ok,
        f"winner {winner!r} not in {sorted(scenario.acceptable_slugs)}"
        if not ok
        else f"{winner} ok",
    )


def check_preference_fit_applied(
    scenario: Scenario, scored: list[ScoredDestination]
) -> InvariantResult:
    """When a scenario declares preferred_trip_types via profile_overrides,
    every scored destination matching one of those trip types should show
    a nonzero preference_fit - the actual PREFERENCE_FIT_BONUS this
    traveler's profile earns, not zero as if they were anonymous."""
    preferred = set((scenario.profile_overrides or {}).get("preferred_trip_types") or ())
    if not preferred:
        return InvariantResult("preference_fit_applied", True, "no preference declared")
    violators = [
        s.destination.slug
        for s in scored
        if s.destination.trip_type in preferred and s.preference_fit <= 0
    ]
    return InvariantResult(
        "preference_fit_applied",
        not violators,
        f"matching trip_type but preference_fit<=0: {violators}" if violators else "clean",
    )


def check_repetition_penalty_applied(
    scenario: Scenario, scored: list[ScoredDestination]
) -> InvariantResult:
    """When a scenario declares completed_trip_slugs/travel_history_slugs
    via profile_overrides, any of those destinations that still survives
    hard constraints should show a nonzero repetition_penalty."""
    overrides = scenario.profile_overrides or {}
    visited = set(overrides.get("completed_trip_slugs") or ()) | set(
        overrides.get("travel_history_slugs") or ()
    )
    if not visited:
        return InvariantResult("repetition_penalty_applied", True, "no travel history declared")
    violators = [
        s.destination.slug
        for s in scored
        if s.destination.slug in visited and s.repetition_penalty <= 0
    ]
    return InvariantResult(
        "repetition_penalty_applied",
        not violators,
        f"previously visited but repetition_penalty<=0: {violators}" if violators else "clean",
    )


def check_zero_results_expectation(
    scenario: Scenario, scored: list[ScoredDestination]
) -> InvariantResult:
    if not scenario.expects_zero_results:
        return InvariantResult("zero_results_expectation", True, "not applicable")
    ok = len(scored) == 0
    return InvariantResult(
        "zero_results_expectation",
        ok,
        "clean" if ok else f"expected zero, got {len(scored)}",
    )


def check_clarification_expectation(
    scenario: Scenario, scored: list[ScoredDestination]
) -> InvariantResult:
    """Distinct from zero_results_expectation - this is "not enough
    signal was ever stated" (has_enough_signal is False, so scoring
    should never even be reached), not "scoring ran and genuinely found
    nothing." Kept separate so a mix-up between the two shows up as a
    specific, readable failure rather than a generic "wrong branch"."""
    if not scenario.expects_clarification:
        return InvariantResult("clarification_expectation", True, "not applicable")
    ok = len(scored) == 0
    return InvariantResult(
        "clarification_expectation",
        ok,
        "clean" if ok else f"expected a clarifying question, got {len(scored)} recommendation(s)",
    )


# --- Structural invariants: checked once, not per scenario - these are
# about what data CAN reach the scoring layer, not about any one run's
# output. ---

_FORBIDDEN_SIGNAL_NAMES = (
    "affiliate",
    "commission",
    "click",
    "acquisition",
    "campaign",
    "utm",
    "referrer",
    "provider_availability",
)


def check_no_affiliate_or_acquisition_signal_in_scoring() -> InvariantResult:
    """Confirms, by inspecting the real function/dataclass signatures (not
    by re-reading a comment), that nothing shaped like affiliate,
    click-through, or acquisition data can be passed into scoring at all.
    recommendations/scoring.py:52-66 documents this as a deliberate
    boundary; this check makes the claim machine-verifiable rather than
    trusting the comment to stay true forever."""
    names = set()
    names.update(inspect.signature(generate_recommendations).parameters)
    names.update(RecommendationRequest.__dataclass_fields__)
    hits = [n for n in names if any(bad in n.lower() for bad in _FORBIDDEN_SIGNAL_NAMES)]
    return InvariantResult(
        "no_affiliate_or_acquisition_signal_in_scoring",
        not hits,
        f"suspicious field(s) found: {hits}" if hits else "clean",
    )


def run_scenario_invariants(
    scenario: Scenario, scored: list[ScoredDestination]
) -> list[InvariantResult]:
    """The standard per-scenario invariant set - everything that only
    needs the scenario's own declared ground truth and the scored
    output, no extra AI/DB calls. check_ranking_deterministic_for_identical_input
    is intentionally not included here (it re-runs scoring, called
    separately by the runner for a sampled subset)."""
    return [
        check_excluded_destinations_absent(scenario, scored),
        check_must_not_include_absent(scenario, scored),
        check_hard_budget_respected(scenario, scored),
        check_temperature_bounds_respected(scenario, scored),
        check_trip_type_respected(scenario, scored),
        check_ranking_sorted_descending(scored),
        check_acceptable_slugs_if_declared(scenario, scored),
        check_zero_results_expectation(scenario, scored),
        check_clarification_expectation(scenario, scored),
        check_preference_fit_applied(scenario, scored),
        check_repetition_penalty_applied(scenario, scored),
    ]
