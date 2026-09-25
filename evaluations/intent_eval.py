"""Intent-extraction accuracy: compares ai.orchestration's real extracted
intent dict against a scenario's declared expected_intent, field by
field. Exists so a ranking failure caused by bad extraction is never
misdiagnosed as a scoring failure - the two are measured independently.
"""

from __future__ import annotations

from dataclasses import dataclass

from .scenarios import Scenario


@dataclass(frozen=True)
class FieldComparison:
    field: str
    expected: object
    actual: object
    matches: bool


@dataclass(frozen=True)
class IntentEvalResult:
    scenario_id: str
    comparisons: tuple[FieldComparison, ...]

    @property
    def accuracy(self) -> float:
        if not self.comparisons:
            return 1.0
        return sum(c.matches for c in self.comparisons) / len(self.comparisons)

    @property
    def all_match(self) -> bool:
        return all(c.matches for c in self.comparisons)

    def to_json(self) -> dict:
        return {
            "scenario_id": self.scenario_id,
            "accuracy": self.accuracy,
            "fields": [
                {"field": c.field, "expected": c.expected, "actual": c.actual, "matches": c.matches}
                for c in self.comparisons
            ],
        }


def _values_match(expected, actual) -> bool:
    if isinstance(expected, list | tuple) and isinstance(actual, list | tuple):
        return set(expected) == set(actual)
    if isinstance(expected, float) or isinstance(actual, float):
        try:
            return abs(float(expected) - float(actual)) < 1e-6
        except (TypeError, ValueError):
            return expected == actual
    return expected == actual


def evaluate_intent(scenario: Scenario, actual_intent: dict) -> IntentEvalResult:
    comparisons = tuple(
        FieldComparison(
            field=field_name,
            expected=expected_value,
            actual=actual_intent.get(field_name),
            matches=_values_match(expected_value, actual_intent.get(field_name)),
        )
        for field_name, expected_value in scenario.expected_intent.items()
    )
    return IntentEvalResult(scenario_id=scenario.id, comparisons=comparisons)


def aggregate_field_accuracy(results: list[IntentEvalResult]) -> dict[str, float]:
    """Per-field accuracy across every scenario that asserted that field,
    e.g. {'month': 0.94, 'max_cost_of_living': 0.81, ...} - only fields
    at least one scenario actually checks appear here."""
    totals: dict[str, int] = {}
    matches: dict[str, int] = {}
    for result in results:
        for c in result.comparisons:
            totals[c.field] = totals.get(c.field, 0) + 1
            matches[c.field] = matches.get(c.field, 0) + int(c.matches)
    return {field_name: matches[field_name] / totals[field_name] for field_name in totals}
