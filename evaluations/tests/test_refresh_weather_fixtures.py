from django.core.management import call_command
from django.test import TestCase

from evaluations.conversation_scenarios import ConversationScenario, ConversationTurn
from evaluations.management.commands.refresh_weather_fixtures import (
    _effective_base_request,
    _months_to_check,
    _relaxed_requests,
    compute_conversation_needed_keys,
    compute_needed_keys,
)
from evaluations.scenarios import Scenario, load_corpus
from evaluations.weather_fixtures import fixture_key
from travel.models import Destination


def _destination(slug, **kwargs):
    defaults = dict(
        name=slug,
        country="Testland",
        latitude=10.0,
        longitude=10.0,
        trip_type="beach",
        cost_of_living=2,
        best_season="x",
        worst_season="x",
        short_description="x",
        points_of_interest=[],
    )
    defaults.update(kwargs)
    return Destination.objects.create(slug=slug, **defaults)


def _scenario(**overrides) -> Scenario:
    defaults = dict(
        id="TST-001",
        split="dev",
        category="straightforward",
        message="test message",
        expected_flow="recommendation",
    )
    defaults.update(overrides)
    return Scenario(**defaults)


class EffectiveBaseRequestTests(TestCase):
    def test_uses_deterministic_request_verbatim_when_present(self):
        scenario = _scenario(
            deterministic_request={"month": 6, "trip_type": "beach", "excluded_slugs": []}
        )
        self.assertEqual(_effective_base_request(scenario), scenario.deterministic_request)

    def test_returns_none_for_a_scenario_that_never_reaches_scoring(self):
        # A visa/booking/off-topic/etc scenario has no deterministic_request
        # and shouldn't get one manufactured from expected_intent either -
        # nothing about it ever reaches recommendations.scoring.
        scenario = _scenario(
            expected_flow="visa", deterministic_request=None, expected_intent={"month": 6}
        )
        self.assertIsNone(_effective_base_request(scenario))

    def test_synthesizes_a_request_from_expected_intent_when_no_deterministic_request(self):
        # Mirrors MTT-007's real shape: a multi-turn scenario whose real
        # request only exists via conversation context, so there's no
        # deterministic_request, but it does reach scoring in a full run.
        scenario = _scenario(
            deterministic_request=None,
            expected_flow="recommendation",
            expected_intent={"month": 10},
        )
        request = _effective_base_request(scenario)
        self.assertEqual(request["month"], 10)
        self.assertIsNone(request["trip_type"])
        self.assertEqual(request["excluded_slugs"], [])

    def test_resolves_excluded_place_names_to_real_slugs(self):
        destination = _destination("marrakech-ma", country="Morocco")
        scenario = _scenario(
            deterministic_request=None,
            expected_flow="recommendation",
            expected_intent={"excluded_place_names": ["Marrakech"]},
        )
        request = _effective_base_request(scenario)
        self.assertIn(destination.slug, request["excluded_slugs"])


class RelaxedRequestsTests(TestCase):
    def test_no_relaxation_needed_when_nothing_to_relax(self):
        base = {"month": 6, "country": "Japan"}
        self.assertEqual(_relaxed_requests(base), [base])

    def test_adds_a_variant_dropping_trip_type_and_budget(self):
        base = {"month": 6, "trip_type": "city", "max_cost_of_living": 3}
        variants = _relaxed_requests(base)
        self.assertEqual(len(variants), 2)
        self.assertEqual(variants[0], base)
        self.assertIsNone(variants[1]["trip_type"])
        self.assertIsNone(variants[1]["max_cost_of_living"])
        # Everything else about the request is preserved, not dropped too.
        self.assertEqual(variants[1]["month"], 6)


class MonthsToCheckTests(TestCase):
    def test_a_stated_month_is_the_only_one_checked(self):
        self.assertEqual(_months_to_check({"month": 4}), [4])

    def test_no_stated_month_checks_every_month(self):
        self.assertEqual(_months_to_check({"month": None}), list(range(1, 13)))
        self.assertEqual(_months_to_check({}), list(range(1, 13)))


class ComputeNeededKeysTests(TestCase):
    def test_a_destination_outside_the_strict_filter_is_still_captured_via_relaxation(self):
        # Mirrors MET-003b: a "nature, mid-range budget" scenario whose real
        # full-pipeline extraction can land one budget tier looser than the
        # scenario's own asserted max_cost_of_living - so a real candidate
        # destination just above that tier must still get a fixture entry.
        strict_match = _destination("cheap-nature", trip_type="nature", cost_of_living=2)
        pricier_match = _destination("pricier-nature", trip_type="nature", cost_of_living=4)
        scenario = _scenario(
            deterministic_request={
                "month": 3,
                "trip_type": "nature",
                "max_cost_of_living": 3,
                "excluded_slugs": [],
            }
        )
        needed = compute_needed_keys([scenario])
        for destination in (strict_match, pricier_match):
            key = fixture_key(float(destination.latitude), float(destination.longitude), 3)
            self.assertIn(key, needed, f"{destination.slug} missing from needed keys")

    def test_country_stays_a_hard_filter_even_when_relaxed(self):
        # Relaxation only ever drops trip_type/budget - a scenario scoped to
        # one country should never pull in a same-trip-type destination from
        # an unrelated country, even in the relaxed pass.
        in_country = _destination(
            "kyoto-like", country="Japan", trip_type="culture", latitude=35.0, longitude=135.0
        )
        elsewhere = _destination(
            "unrelated-nature", country="Peru", trip_type="nature", latitude=-13.0, longitude=-72.0
        )
        scenario = _scenario(
            deterministic_request={
                "month": 10,
                "trip_type": "city",
                "country": "Japan",
                "excluded_slugs": [],
            }
        )
        needed = compute_needed_keys([scenario])
        in_key = fixture_key(float(in_country.latitude), float(in_country.longitude), 10)
        out_key = fixture_key(float(elsewhere.latitude), float(elsewhere.longitude), 10)
        self.assertIn(in_key, needed)
        self.assertNotIn(out_key, needed)

    def test_a_scenario_with_no_deterministic_request_still_gets_covered(self):
        # Mirrors MTT-007/ROB-015's shape - previously silently skipped
        # entirely (deterministic_request is None), even though a full run
        # does reach real scoring for these.
        destination = _destination("some-city", trip_type="city")
        scenario = _scenario(
            deterministic_request=None,
            expected_flow="recommendation",
            expected_intent={"trip_type": "city"},
        )
        needed = compute_needed_keys([scenario])
        self.assertTrue(any(key.endswith(f",{month}") for key in needed for month in range(1, 13)))
        found = any(
            key == fixture_key(float(destination.latitude), float(destination.longitude), month)
            for key in needed
            for month in range(1, 13)
        )
        self.assertTrue(found)

    def test_an_unasserted_month_covers_every_month(self):
        destination = _destination("month-agnostic", trip_type="city")
        scenario = _scenario(
            deterministic_request=None,
            expected_flow="recommendation",
            expected_intent={"trip_type": "city"},
        )
        needed = compute_needed_keys([scenario])
        for month in range(1, 13):
            key = fixture_key(float(destination.latitude), float(destination.longitude), month)
            self.assertIn(key, needed, f"month {month} missing")

    def test_a_scenario_that_never_reaches_scoring_contributes_no_keys(self):
        _destination("irrelevant")
        scenario = _scenario(
            expected_flow="visa", deterministic_request=None, expected_intent={"month": 6}
        )
        self.assertEqual(compute_needed_keys([scenario]), {})


class RealCorpusRegressionTests(TestCase):
    """Ties the fix directly to the four scenarios that were actually
    reported as DEPENDENCY_FAILURE in a real full-pipeline run
    (20260928-090035_cycle1_verified_full) despite the fixture covering
    everything the old targeting logic thought it needed. Needs the real
    catalog loaded - compute_needed_keys queries Destination.objects, and
    these four keys only get targeted once the real destinations at those
    coordinates are actually in the DB."""

    @classmethod
    def setUpTestData(cls):
        call_command("load_destinations")

    def test_previously_missing_keys_are_now_targeted(self):
        needed = compute_needed_keys(load_corpus())
        previously_missing = [
            fixture_key(51.18, -115.57, 3),  # MET-003b
            fixture_key(36.39, 25.46, 10),  # MTT-007
            fixture_key(35.01, 135.77, 10),  # MTT-010
            fixture_key(38.72, -9.14, 7),  # ROB-015
        ]
        for key in previously_missing:
            self.assertIn(key, needed, f"{key} still not targeted for capture")


class ComputeConversationNeededKeysTests(TestCase):
    def test_targets_a_checkpoint_turns_candidate_destinations(self):
        destination = _destination("beach-1", trip_type="beach", latitude=5.0, longitude=5.0)
        conversation = ConversationScenario(
            id="X-1",
            split="dev",
            family="drift",
            turns=(
                ConversationTurn(message="a", expected_state={"month": 6, "trip_type": "beach"}),
                ConversationTurn(message="b"),
            ),
        )
        needed = compute_conversation_needed_keys([conversation])
        key = fixture_key(float(destination.latitude), float(destination.longitude), 6)
        self.assertIn(key, needed)

    def test_ignores_turns_with_no_checkpoint(self):
        conversation = ConversationScenario(
            id="X-1",
            split="dev",
            family="drift",
            turns=(ConversationTurn(message="a"), ConversationTurn(message="b")),
        )
        self.assertEqual(compute_conversation_needed_keys([conversation]), {})
