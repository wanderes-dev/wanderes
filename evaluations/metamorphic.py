"""Metamorphic testing (§11): take the same traveler, vary exactly one
axis, and check whether the eligible/ranked set changes in a direction
the real scoring code actually guarantees - not a direction we merely
expect from domain intuition.

Only four axes have a provable structural guarantee given
recommendations/scoring.py's actual filter chain, with everything else
held equal:

- Loosening max_cost_of_living (raising the ceiling) can only ever grow
  the DB-level-eligible set (the `cost_of_living__lte` filter is a pure
  narrowing operation) - the eligible set at the higher budget is always
  a superset of the eligible set at the lower one.
- Raising min_temp_c (or lowering max_temp_c) - a stricter climate bound
  - can only ever shrink the post-climate-filter eligible set.
- Narrowing continent -> a specific country only ever shrinks the
  eligible set (country is applied as an additional, more specific
  filter on top of continent's).
- Adding one more excluded_slug removes exactly that slug from the
  eligible set (`.exclude(slug__in=...)` runs before every other filter)
  and changes nothing else.

A month change or a trip_type change has NO such guarantee - real-world
climate isn't monotonic across months (and inverts by hemisphere), and
trip_type is a categorical re-filter, not an ordering. Those axes are
still run and recorded (top winner, eligible-set Jaccard similarity) as
informational stability observations, per §11's "explicitly report
unexpected invariance or unexpected instability" - never turned into a
pass/fail invariant not actually backed by the code.
"""

from __future__ import annotations

from dataclasses import dataclass

from recommendations.scoring import generate_recommendations

from .invariants import InvariantResult
from .requests import build_request
from .scenarios import Scenario

# Axes with a provable monotonic direction. "grows"/"shrinks" describes
# how scenario_b's eligible set relates to scenario_a's (b is the
# looser/stricter side, per the axis name).
MONOTONIC_AXES = {
    "budget_loosen": "grows",
    "budget_tighten": "shrinks",
    "temperature_bound_loosen": "grows",
    "temperature_bound_tighten": "shrinks",
    "geography_narrow": "shrinks",
    "add_exclusion": "shrinks_by_exactly_excluded",
}


@dataclass(frozen=True)
class MetamorphicComparison:
    pair_id: str
    axis: str | None
    scenario_a_id: str
    scenario_b_id: str
    winner_a: str | None
    winner_b: str | None
    eligible_a: frozenset
    eligible_b: frozenset
    jaccard_similarity: float
    checks: tuple[InvariantResult, ...]

    def to_json(self) -> dict:
        return {
            "pair_id": self.pair_id,
            "axis": self.axis,
            "scenario_a_id": self.scenario_a_id,
            "scenario_b_id": self.scenario_b_id,
            "winner_a": self.winner_a,
            "winner_b": self.winner_b,
            "eligible_count_a": len(self.eligible_a),
            "eligible_count_b": len(self.eligible_b),
            "jaccard_similarity": self.jaccard_similarity,
            "checks": [
                {"name": c.name, "passed": c.passed, "detail": c.detail} for c in self.checks
            ],
        }


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


def _monotonic_check(axis: str, eligible_a: frozenset, eligible_b: frozenset) -> InvariantResult:
    direction = MONOTONIC_AXES[axis]
    if direction == "grows":
        ok = eligible_a.issubset(eligible_b)
        return InvariantResult(
            f"metamorphic_{axis}",
            ok,
            "clean"
            if ok
            else f"expected b to be a superset of a; lost: {sorted(eligible_a - eligible_b)}",
        )
    if direction == "shrinks":
        ok = eligible_b.issubset(eligible_a)
        return InvariantResult(
            f"metamorphic_{axis}",
            ok,
            "clean"
            if ok
            else f"expected b to be a subset of a; gained: {sorted(eligible_b - eligible_a)}",
        )
    raise ValueError(f"unhandled monotonic direction {direction!r} for axis {axis!r}")


def _exclusion_check(
    scenario_a: Scenario, scenario_b: Scenario, eligible_a, eligible_b
) -> InvariantResult:
    excluded_a = set((scenario_a.deterministic_request or {}).get("excluded_slugs") or ())
    excluded_b = set((scenario_b.deterministic_request or {}).get("excluded_slugs") or ())
    newly_excluded = excluded_b - excluded_a
    expected_b = eligible_a - newly_excluded
    ok = eligible_b == expected_b
    return InvariantResult(
        "metamorphic_add_exclusion",
        ok,
        "clean" if ok else f"expected {sorted(expected_b)}, got {sorted(eligible_b)}",
    )


def run_metamorphic_pair(
    scenario_a: Scenario, scenario_b: Scenario, *, climate_provider
) -> MetamorphicComparison:
    """Runs both sides of a pair through deterministic scoring only (each
    scenario's own deterministic_request ground truth, no AI calls) -
    isolates the metamorphic property to the scoring layer, the only
    layer with an actual structural guarantee to check."""
    if scenario_a.metamorphic_pair != scenario_b.metamorphic_pair:
        raise ValueError(f"{scenario_a.id} and {scenario_b.id} are not the same metamorphic pair")

    request_a = build_request(scenario_a.deterministic_request)
    request_b = build_request(scenario_b.deterministic_request)
    scored_a = generate_recommendations(request_a, climate_provider=climate_provider)
    scored_b = generate_recommendations(request_b, climate_provider=climate_provider)
    eligible_a = frozenset(s.destination.slug for s in scored_a)
    eligible_b = frozenset(s.destination.slug for s in scored_b)

    axis = scenario_a.metamorphic_axis or scenario_b.metamorphic_axis
    checks: list[InvariantResult] = []
    if axis == "add_exclusion":
        checks.append(_exclusion_check(scenario_a, scenario_b, eligible_a, eligible_b))
    elif axis in MONOTONIC_AXES:
        checks.append(_monotonic_check(axis, eligible_a, eligible_b))
    # Any other axis (month_change, trip_type_change, ...) gets no
    # pass/fail check - only the observation below, by design (see
    # module docstring).

    return MetamorphicComparison(
        pair_id=scenario_a.metamorphic_pair,
        axis=axis,
        scenario_a_id=scenario_a.id,
        scenario_b_id=scenario_b.id,
        winner_a=scored_a[0].destination.slug if scored_a else None,
        winner_b=scored_b[0].destination.slug if scored_b else None,
        eligible_a=eligible_a,
        eligible_b=eligible_b,
        jaccard_similarity=_jaccard(eligible_a, eligible_b),
        checks=tuple(checks),
    )
