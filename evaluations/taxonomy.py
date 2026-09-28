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
    # Cycle 1.5 (2026-09-25): a third party's own availability/rate limit
    # (missing weather fixture, a live provider timeout/429/5xx when
    # explicitly run against the network) - never counted toward product-
    # quality categories above, and excluded from the quality pass/fail
    # denominator entirely (evaluations.runner/persistence). Exists
    # because Cycle 1's own comparison run got contaminated exactly this
    # way: Open-Meteo's daily quota ran out mid-run and several scenarios
    # were reported as SCORING failures despite perfect extraction and
    # unrelated production code.
    DEPENDENCY_FAILURE = "DEPENDENCY_FAILURE"
    # Cycle 2 (multi-turn conversation evaluation) - a single-request
    # scenario has no notion of "the traveler already told us this," so
    # these categories didn't exist until a conversation corpus needed to
    # distinguish *why* state was wrong at a given turn, not just that it
    # was.
    LOST_CONTEXT = "LOST_CONTEXT"  # an unsuperseded earlier value silently reverted to null/default
    STALE_STATE = "STALE_STATE"  # a superseded value reappeared as if never superseded
    CORRECTION_FAILURE = "CORRECTION_FAILURE"  # a same-turn-family correction didn't take
    CONTRADICTION_RESOLUTION = (
        "CONTRADICTION_RESOLUTION"  # a later, contradicting statement didn't win
    )
    REFERENCE_RESOLUTION = (
        "REFERENCE_RESOLUTION"  # "the second option" etc. resolved wrong or not at all
    )
    EXCLUSION_PERSISTENCE = (
        "EXCLUSION_PERSISTENCE"  # an explicit exclusion didn't hold at a later turn
    )
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
    "dependency_failure": FailureCategory.DEPENDENCY_FAILURE,
    # Cycle 2 conversation-level checks whose category is fixed regardless
    # of which turn/field they fired on. checkpoint_state:<field> is
    # deliberately NOT here - its category depends on comparing the wrong
    # value against the conversation's own earlier checkpoints (stale vs.
    # lost vs. a plain miss), which only evaluations.conversation_runner
    # has the context to resolve; see classify_checkpoint_failure there.
    "correction_field_superseded": FailureCategory.CORRECTION_FAILURE,
    "contradiction_resolved": FailureCategory.CONTRADICTION_RESOLUTION,
    "reference_resolved": FailureCategory.REFERENCE_RESOLUTION,
    "exclusion_still_persists": FailureCategory.EXCLUSION_PERSISTENCE,
    "irrelevant_information_stable": FailureCategory.INTENT_EXTRACTION,
    "clarification_not_forced": FailureCategory.MISSING_INFORMATION,
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
