from django.test import TestCase

from evaluations.metamorphic import run_metamorphic_pair
from evaluations.scenarios import Scenario
from integrations.climate.base import MonthlyClimateSummary
from travel.models import Destination


class _StubClimate:
    def get_monthly_climate(self, *, latitude, longitude, month, year=None):
        return MonthlyClimateSummary(2025, month, 25.0, 18.0, 5.0)


def _destination(slug, *, cost_of_living, trip_type="beach", country="Testland"):
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


def _pair_scenario(suffix, deterministic_request, axis):
    return Scenario(
        id=f"MET-TEST{suffix}",
        split="dev",
        category="metamorphic",
        message="test",
        deterministic_request=deterministic_request,
        metamorphic_pair="MET-TEST",
        metamorphic_axis=axis,
    )


class BudgetLoosenTests(TestCase):
    def test_looser_budget_is_a_superset(self):
        _destination("cheap", cost_of_living=1)
        _destination("mid", cost_of_living=3)
        _destination("expensive", cost_of_living=5)
        scenario_a = _pair_scenario("a", {"month": 6, "max_cost_of_living": 2}, "budget_loosen")
        scenario_b = _pair_scenario("b", {"month": 6, "max_cost_of_living": 4}, "budget_loosen")

        comparison = run_metamorphic_pair(scenario_a, scenario_b, climate_provider=_StubClimate())

        self.assertTrue(all(c.passed for c in comparison.checks))
        self.assertIn("cheap", comparison.eligible_a)
        self.assertIn("mid", comparison.eligible_b)
        self.assertNotIn("expensive", comparison.eligible_b)


class AddExclusionTests(TestCase):
    def test_exclusion_removes_exactly_that_slug(self):
        _destination("keep-me", cost_of_living=1)
        _destination("exclude-me", cost_of_living=1)
        scenario_a = _pair_scenario("a", {"month": 6}, "add_exclusion")
        scenario_b = _pair_scenario(
            "b", {"month": 6, "excluded_slugs": ["exclude-me"]}, "add_exclusion"
        )

        comparison = run_metamorphic_pair(scenario_a, scenario_b, climate_provider=_StubClimate())

        self.assertTrue(all(c.passed for c in comparison.checks))
        self.assertEqual(comparison.eligible_b, comparison.eligible_a - {"exclude-me"})


class NonMonotonicAxisTests(TestCase):
    def test_month_change_produces_no_checks(self):
        _destination("a", cost_of_living=1)
        scenario_a = _pair_scenario("a", {"month": 6}, "month_change")
        scenario_b = _pair_scenario("b", {"month": 12}, "month_change")

        comparison = run_metamorphic_pair(scenario_a, scenario_b, climate_provider=_StubClimate())

        self.assertEqual(comparison.checks, ())


class MismatchedPairTests(TestCase):
    def test_raises_when_pair_ids_differ(self):
        scenario_a = Scenario(
            id="A",
            split="dev",
            category="metamorphic",
            message="x",
            deterministic_request={"month": 6},
            metamorphic_pair="P1",
        )
        scenario_b = Scenario(
            id="B",
            split="dev",
            category="metamorphic",
            message="y",
            deterministic_request={"month": 6},
            metamorphic_pair="P2",
        )
        with self.assertRaises(ValueError):
            run_metamorphic_pair(scenario_a, scenario_b, climate_provider=_StubClimate())
