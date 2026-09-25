from django.test import TestCase

from evaluations.invariants import (
    check_acceptable_slugs_if_declared,
    check_clarification_expectation,
    check_excluded_destinations_absent,
    check_hard_budget_respected,
    check_must_not_include_absent,
    check_no_affiliate_or_acquisition_signal_in_scoring,
    check_preference_fit_applied,
    check_ranking_deterministic_for_identical_input,
    check_ranking_sorted_descending,
    check_repetition_penalty_applied,
    check_temperature_bounds_respected,
    check_trip_type_respected,
    check_zero_results_expectation,
)
from evaluations.requests import build_request
from evaluations.scenarios import Scenario
from recommendations.scoring import ScoredDestination
from travel.models import Destination


def _destination(slug, *, country="Testland", trip_type="beach", cost_of_living=2):
    return Destination.objects.create(
        slug=slug,
        name=slug,
        country=country,
        latitude=10.0,
        longitude=10.0,
        trip_type=trip_type,
        cost_of_living=cost_of_living,
        best_season="Jan-Dec",
        worst_season="None",
        short_description="Test.",
        points_of_interest=[],
    )


def _scored(destination, *, score=1.0, avg_high_c=25.0, preference_fit=0.0, repetition_penalty=0.0):
    return ScoredDestination(
        destination=destination,
        avg_high_c=avg_high_c,
        avg_low_c=avg_high_c - 5 if avg_high_c is not None else None,
        preference_fit=preference_fit,
        budget_fit=0.0,
        temperature_fit=0.0,
        repetition_penalty=repetition_penalty,
        score=score,
    )


def _scenario(**kwargs):
    defaults = {"id": "T-1", "split": "dev", "category": "straightforward", "message": "test"}
    defaults.update(kwargs)
    return Scenario(**defaults)


class ExcludedDestinationsAbsentTests(TestCase):
    def test_passes_when_no_exclusion_declared(self):
        result = check_excluded_destinations_absent(_scenario(), [])
        self.assertTrue(result.passed)

    def test_fails_when_excluded_destination_present(self):
        d = _destination("bad-slug")
        scenario = _scenario(deterministic_request={"month": 6, "excluded_slugs": ["bad-slug"]})
        result = check_excluded_destinations_absent(scenario, [_scored(d)])
        self.assertFalse(result.passed)
        self.assertIn("bad-slug", result.detail)

    def test_passes_when_excluded_destination_absent(self):
        d = _destination("ok-slug")
        scenario = _scenario(deterministic_request={"month": 6, "excluded_slugs": ["other-slug"]})
        result = check_excluded_destinations_absent(scenario, [_scored(d)])
        self.assertTrue(result.passed)


class MustNotIncludeAbsentTests(TestCase):
    def test_fails_when_forbidden_destination_present(self):
        d = _destination("forbidden")
        scenario = _scenario(must_not_include_slugs=("forbidden",))
        result = check_must_not_include_absent(scenario, [_scored(d)])
        self.assertFalse(result.passed)


class HardBudgetRespectedTests(TestCase):
    def test_fails_when_over_ceiling(self):
        d = _destination("expensive", cost_of_living=5)
        scenario = _scenario(deterministic_request={"month": 6, "max_cost_of_living": 2})
        result = check_hard_budget_respected(scenario, [_scored(d)])
        self.assertFalse(result.passed)

    def test_passes_when_within_ceiling(self):
        d = _destination("cheap", cost_of_living=1)
        scenario = _scenario(deterministic_request={"month": 6, "max_cost_of_living": 2})
        result = check_hard_budget_respected(scenario, [_scored(d)])
        self.assertTrue(result.passed)


class TemperatureBoundsRespectedTests(TestCase):
    def test_fails_when_below_min(self):
        d = _destination("cold")
        scenario = _scenario(deterministic_request={"month": 6, "min_temp_c": 25})
        result = check_temperature_bounds_respected(scenario, [_scored(d, avg_high_c=10.0)])
        self.assertFalse(result.passed)

    def test_fails_when_above_max(self):
        d = _destination("hot")
        scenario = _scenario(deterministic_request={"month": 6, "max_temp_c": 20})
        result = check_temperature_bounds_respected(scenario, [_scored(d, avg_high_c=35.0)])
        self.assertFalse(result.passed)

    def test_ignores_missing_avg_high_c(self):
        d = _destination("unknown-climate")
        scenario = _scenario(deterministic_request={"month": 6, "min_temp_c": 25})
        result = check_temperature_bounds_respected(scenario, [_scored(d, avg_high_c=None)])
        self.assertTrue(result.passed)


class TripTypeRespectedTests(TestCase):
    def test_fails_when_wrong_trip_type_present(self):
        d = _destination("wrong-type", trip_type="city")
        scenario = _scenario(deterministic_request={"month": 6, "trip_type": "beach"})
        result = check_trip_type_respected(scenario, [_scored(d)])
        self.assertFalse(result.passed)


class RankingSortedDescendingTests(TestCase):
    def test_passes_for_sorted_scores(self):
        d1, d2 = _destination("a"), _destination("b")
        result = check_ranking_sorted_descending([_scored(d1, score=5.0), _scored(d2, score=1.0)])
        self.assertTrue(result.passed)

    def test_fails_for_unsorted_scores(self):
        d1, d2 = _destination("a"), _destination("b")
        result = check_ranking_sorted_descending([_scored(d1, score=1.0), _scored(d2, score=5.0)])
        self.assertFalse(result.passed)


class RankingDeterministicTests(TestCase):
    def test_identical_input_produces_identical_order(self):
        _destination("a", trip_type="beach")
        _destination("b", trip_type="beach")
        request = build_request({"month": 6, "trip_type": "beach"})
        result = check_ranking_deterministic_for_identical_input(
            request, climate_provider=_StubClimate()
        )
        self.assertTrue(result.passed)


class _StubClimate:
    def get_monthly_climate(self, *, latitude, longitude, month, year=None):
        from integrations.climate.base import MonthlyClimateSummary

        return MonthlyClimateSummary(2025, month, 25.0, 18.0, 5.0)


class AcceptableSlugsTests(TestCase):
    def test_passes_when_no_whitelist_declared(self):
        result = check_acceptable_slugs_if_declared(_scenario(), [])
        self.assertTrue(result.passed)

    def test_fails_when_winner_not_in_whitelist(self):
        d = _destination("not-whitelisted")
        scenario = _scenario(acceptable_slugs=("other",))
        result = check_acceptable_slugs_if_declared(scenario, [_scored(d)])
        self.assertFalse(result.passed)

    def test_fails_when_nothing_recommended_but_whitelist_declared(self):
        scenario = _scenario(acceptable_slugs=("something",))
        result = check_acceptable_slugs_if_declared(scenario, [])
        self.assertFalse(result.passed)


class ZeroResultsAndClarificationTests(TestCase):
    def test_zero_results_expectation_fails_when_results_present(self):
        d = _destination("unexpected")
        scenario = _scenario(expects_zero_results=True)
        result = check_zero_results_expectation(scenario, [_scored(d)])
        self.assertFalse(result.passed)

    def test_clarification_expectation_fails_when_results_present(self):
        d = _destination("unexpected")
        scenario = _scenario(expects_clarification=True)
        result = check_clarification_expectation(scenario, [_scored(d)])
        self.assertFalse(result.passed)

    def test_both_pass_trivially_when_not_declared(self):
        scenario = _scenario()
        self.assertTrue(check_zero_results_expectation(scenario, []).passed)
        self.assertTrue(check_clarification_expectation(scenario, []).passed)


class PreferenceFitAndRepetitionPenaltyTests(TestCase):
    def test_preference_fit_fails_when_matching_type_has_zero_bonus(self):
        d = _destination("beach-1", trip_type="beach")
        scenario = _scenario(profile_overrides={"preferred_trip_types": ["beach"]})
        result = check_preference_fit_applied(scenario, [_scored(d, preference_fit=0.0)])
        self.assertFalse(result.passed)

    def test_preference_fit_passes_when_bonus_applied(self):
        d = _destination("beach-1", trip_type="beach")
        scenario = _scenario(profile_overrides={"preferred_trip_types": ["beach"]})
        result = check_preference_fit_applied(scenario, [_scored(d, preference_fit=2.0)])
        self.assertTrue(result.passed)

    def test_repetition_penalty_fails_when_visited_destination_has_zero_penalty(self):
        d = _destination("visited-1")
        scenario = _scenario(profile_overrides={"completed_trip_slugs": ["visited-1"]})
        result = check_repetition_penalty_applied(scenario, [_scored(d, repetition_penalty=0.0)])
        self.assertFalse(result.passed)

    def test_repetition_penalty_passes_when_applied(self):
        d = _destination("visited-1")
        scenario = _scenario(profile_overrides={"completed_trip_slugs": ["visited-1"]})
        result = check_repetition_penalty_applied(scenario, [_scored(d, repetition_penalty=3.0)])
        self.assertTrue(result.passed)


class StructuralInvariantTests(TestCase):
    def test_no_affiliate_or_acquisition_signal_in_scoring(self):
        result = check_no_affiliate_or_acquisition_signal_in_scoring()
        self.assertTrue(result.passed, result.detail)
