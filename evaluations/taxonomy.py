"""Failure taxonomy: buckets a specific failed check into a category so
engineering effort gets prioritized by where problems actually cluster
(§16 of the evaluation spec), not by anecdote. A static name->category
mapping, not an AI judgment call - keeps the taxonomy itself
reproducible and auditable run over run.
"""

from __future__ import annotations

from enum import Enum


class FailureCategory(str, Enum):
    INTENT_EXTRACTION = "INTENT_EXTRACTION"
    HARD_CONSTRAINT = "HARD_CONSTRAINT"
    DESTINATION_DATA = "DESTINATION_DATA"
    SCORING = "SCORING"
    RANKING = "RANKING"
    EXPLANATION_GROUNDING = "EXPLANATION_GROUNDING"
    MISSING_INFORMATION = "MISSING_INFORMATION"
    ROBUSTNESS = "ROBUSTNESS"
    UNKNOWN = "UNKNOWN"


# Every deterministic-invariant/grounding-check name this framework
# produces (evaluations.invariants / evaluations.grounding) plus the two
# runner-level pseudo-checks (flow_mismatch, clarification_expectation)
# maps to exactly one bucket.
_CHECK_CATEGORY = {
    "excluded_destinations_absent": FailureCategory.HARD_CONSTRAINT,
    "must_not_include_absent": FailureCategory.HARD_CONSTRAINT,
    "hard_budget_respected": FailureCategory.HARD_CONSTRAINT,
    "temperature_bounds_respected": FailureCategory.HARD_CONSTRAINT,
    "trip_type_respected": FailureCategory.HARD_CONSTRAINT,
    "ranking_sorted_descending": FailureCategory.RANKING,
    "ranking_deterministic_for_identical_input": FailureCategory.RANKING,
    "winner_in_acceptable_set": FailureCategory.SCORING,
    "zero_results_expectation": FailureCategory.SCORING,
    "no_affiliate_or_acquisition_signal_in_scoring": FailureCategory.SCORING,
    "preference_fit_applied": FailureCategory.SCORING,
    "repetition_penalty_applied": FailureCategory.SCORING,
    "winner_mentioned": FailureCategory.EXPLANATION_GROUNDING,
    "no_live_price_claim": FailureCategory.EXPLANATION_GROUNDING,
    "no_availability_claim": FailureCategory.EXPLANATION_GROUNDING,
    "no_provider_consultation_claim": FailureCategory.EXPLANATION_GROUNDING,
    "no_fabricated_rating_or_review": FailureCategory.EXPLANATION_GROUNDING,
    "flow_mismatch": FailureCategory.INTENT_EXTRACTION,
    "clarification_expectation": FailureCategory.MISSING_INFORMATION,
}


def classify_failure(*, check_name: str, scenario_category: str) -> FailureCategory:
    if check_name in _CHECK_CATEGORY:
        return _CHECK_CATEGORY[check_name]
    if check_name.startswith("intent_field:"):
        return FailureCategory.INTENT_EXTRACTION
    if scenario_category == "robustness":
        return FailureCategory.ROBUSTNESS
    return FailureCategory.UNKNOWN


def count_by_category(failure_check_names: list[tuple[str, str]]) -> dict[str, int]:
    """`failure_check_names` is a list of (check_name, scenario_category)
    pairs, one per failed check across a whole run. Returns counts per
    FailureCategory value, only including categories that actually
    occurred."""
    counts: dict[str, int] = {}
    for check_name, scenario_category in failure_check_names:
        category = classify_failure(check_name=check_name, scenario_category=scenario_category)
        counts[category.value] = counts.get(category.value, 0) + 1
    return counts
