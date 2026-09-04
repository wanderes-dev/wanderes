import time
from unittest.mock import patch

from django.test import TestCase

from integrations.climate.base import ClimateProviderError, MonthlyClimateSummary
from recommendations.scoring import RecommendationRequest, generate_recommendations
from travel.models import Destination
from trips.models import TravelHistoryEntry, Trip
from users.models import TravelerProfile, User


class StubClimateProvider:
    """A climate_provider stub keyed by rounded (lat, lon) - avoids network
    calls entirely so the scoring algorithm can be tested in isolation."""

    def __init__(self, climate_by_coords):
        self._climate_by_coords = climate_by_coords

    def get_monthly_climate(self, *, latitude, longitude, month, year=None):
        key = (round(float(latitude), 2), round(float(longitude), 2))
        if key not in self._climate_by_coords:
            raise ClimateProviderError(f"no stub data for {key}")
        return self._climate_by_coords[key]


class CountingClimateProvider(StubClimateProvider):
    """Wraps StubClimateProvider, recording every (lat, lon) actually
    queried - lets a test assert the climate provider was never called for
    a destination that a cheap DB-level filter should have ruled out
    beforehand (2026-09-02 fix)."""

    def __init__(self, climate_by_coords):
        super().__init__(climate_by_coords)
        self.queried_coords = []

    def get_monthly_climate(self, *, latitude, longitude, month, year=None):
        self.queried_coords.append((round(float(latitude), 2), round(float(longitude), 2)))
        return super().get_monthly_climate(
            latitude=latitude, longitude=longitude, month=month, year=year
        )


def _make_destination(slug, *, lat, lon, trip_type="beach", cost_of_living=3, country="Testland"):
    return Destination.objects.create(
        slug=slug,
        name=slug,
        country=country,
        latitude=lat,
        longitude=lon,
        trip_type=trip_type,
        cost_of_living=cost_of_living,
        best_season="Jan-Dec",
        worst_season="None",
        short_description="A test destination.",
        points_of_interest=[],
    )


class GenerateRecommendationsTests(TestCase):
    def setUp(self):
        self.warm_cheap = _make_destination(
            "warm-cheap", lat=10.0, lon=10.0, trip_type="beach", cost_of_living=1
        )
        self.warm_expensive = _make_destination(
            "warm-expensive", lat=20.0, lon=20.0, trip_type="city", cost_of_living=5
        )
        self.cold_cheap = _make_destination(
            "cold-cheap", lat=30.0, lon=30.0, trip_type="nature", cost_of_living=1
        )

        self.climate = StubClimateProvider(
            {
                (10.0, 10.0): MonthlyClimateSummary(2025, 10, 28.0, 20.0, 5.0),
                (20.0, 20.0): MonthlyClimateSummary(2025, 10, 26.0, 18.0, 10.0),
                (30.0, 30.0): MonthlyClimateSummary(2025, 10, 5.0, -2.0, 40.0),
            }
        )

    def test_min_temperature_excludes_cold_destinations(self):
        request = RecommendationRequest(month=10, min_temp_c=20.0)

        results = generate_recommendations(request, climate_provider=self.climate)

        slugs = {r.destination.slug for r in results}
        self.assertEqual(slugs, {"warm-cheap", "warm-expensive"})

    def test_max_cost_of_living_excludes_expensive_destinations(self):
        request = RecommendationRequest(month=10, max_cost_of_living=3)

        results = generate_recommendations(request, climate_provider=self.climate)

        slugs = {r.destination.slug for r in results}
        self.assertEqual(slugs, {"warm-cheap", "cold-cheap"})

    def test_trip_type_excludes_non_matching_destinations(self):
        request = RecommendationRequest(month=10, trip_type="city")

        results = generate_recommendations(request, climate_provider=self.climate)

        slugs = {r.destination.slug for r in results}
        self.assertEqual(slugs, {"warm-expensive"})

    def test_trip_type_filter_skips_climate_lookups_for_non_matching_destinations(self):
        # 2026-09-02 fix: trip_type/max_cost_of_living are applied as real
        # DB-level filters BEFORE any climate provider call, not just as a
        # post-hoc Python check after fetching climate for everything. A
        # real production timeout (reported live, 2026-09-02: "quero neve
        # fim do ano" got a generic error) traced to the old order making
        # an unnecessary real HTTP climate lookup for every non-matching
        # destination first, at the current 384-destination catalog scale.
        counting_climate = CountingClimateProvider(
            {
                (10.0, 10.0): MonthlyClimateSummary(2025, 10, 28.0, 20.0, 5.0),
                (20.0, 20.0): MonthlyClimateSummary(2025, 10, 26.0, 18.0, 10.0),
                (30.0, 30.0): MonthlyClimateSummary(2025, 10, 5.0, -2.0, 40.0),
            }
        )
        request = RecommendationRequest(month=10, trip_type="city")

        results = generate_recommendations(request, climate_provider=counting_climate)

        self.assertEqual({r.destination.slug for r in results}, {"warm-expensive"})
        self.assertEqual(counting_climate.queried_coords, [(20.0, 20.0)])

    def test_max_cost_of_living_filter_skips_climate_lookups_for_expensive_destinations(self):
        counting_climate = CountingClimateProvider(
            {
                (10.0, 10.0): MonthlyClimateSummary(2025, 10, 28.0, 20.0, 5.0),
                (20.0, 20.0): MonthlyClimateSummary(2025, 10, 26.0, 18.0, 10.0),
                (30.0, 30.0): MonthlyClimateSummary(2025, 10, 5.0, -2.0, 40.0),
            }
        )
        request = RecommendationRequest(month=10, max_cost_of_living=3)

        results = generate_recommendations(request, climate_provider=counting_climate)

        self.assertEqual(
            {r.destination.slug for r in results}, {"warm-cheap", "cold-cheap"}
        )
        self.assertEqual(
            sorted(counting_climate.queried_coords), [(10.0, 10.0), (30.0, 30.0)]
        )

    def test_continent_excludes_non_matching_destinations(self):
        # 2026-09-04, real production bug: a "Eurotrip" request's
        # recommendation cards included Bali, Marrakech, and Chiang Mai
        # alongside the genuinely European options - nothing filtered by
        # continent at all before this field existed.
        request = RecommendationRequest(month=10, continent="europe")

        results = generate_recommendations(request, climate_provider=self.climate)

        slugs = {r.destination.slug for r in results}
        self.assertEqual(slugs, set())  # setUp's destinations are all "Testland"

    def test_continent_filter_skips_climate_lookups_for_non_matching_destinations(self):
        _make_destination(
            "lisbon", lat=40.0, lon=-9.0, trip_type="city", cost_of_living=2, country="Portugal"
        )
        bangkok = _make_destination(
            "bangkok", lat=13.0, lon=100.0, trip_type="city", cost_of_living=2, country="Tailândia"
        )
        counting_climate = CountingClimateProvider(
            {
                (40.0, -9.0): MonthlyClimateSummary(2025, 10, 22.0, 15.0, 5.0),
                (13.0, 100.0): MonthlyClimateSummary(2025, 10, 32.0, 24.0, 20.0),
                (10.0, 10.0): MonthlyClimateSummary(2025, 10, 28.0, 20.0, 5.0),
                (20.0, 20.0): MonthlyClimateSummary(2025, 10, 26.0, 18.0, 10.0),
                (30.0, 30.0): MonthlyClimateSummary(2025, 10, 5.0, -2.0, 40.0),
            }
        )
        request = RecommendationRequest(month=10, continent="europe")

        results = generate_recommendations(request, climate_provider=counting_climate)

        self.assertEqual({r.destination.slug for r in results}, {"lisbon"})
        self.assertEqual(counting_climate.queried_coords, [(40.0, -9.0)])
        self.assertNotIn(bangkok.slug, {r.destination.slug for r in results})

    def test_no_continent_applies_no_geographic_filtering(self):
        _make_destination(
            "lisbon", lat=40.0, lon=-9.0, trip_type="city", cost_of_living=2, country="Portugal"
        )
        climate = StubClimateProvider(
            {
                (40.0, -9.0): MonthlyClimateSummary(2025, 10, 22.0, 15.0, 5.0),
                (10.0, 10.0): MonthlyClimateSummary(2025, 10, 28.0, 20.0, 5.0),
                (20.0, 20.0): MonthlyClimateSummary(2025, 10, 26.0, 18.0, 10.0),
                (30.0, 30.0): MonthlyClimateSummary(2025, 10, 5.0, -2.0, 40.0),
            }
        )
        request = RecommendationRequest(month=10)

        results = generate_recommendations(request, climate_provider=climate)

        slugs = {r.destination.slug for r in results}
        self.assertIn("lisbon", slugs)
        self.assertIn("warm-cheap", slugs)

    def test_excluded_slugs_are_removed_from_candidates(self):
        request = RecommendationRequest(month=10, excluded_slugs=frozenset({"warm-cheap"}))

        results = generate_recommendations(request, climate_provider=self.climate)

        slugs = {r.destination.slug for r in results}
        self.assertNotIn("warm-cheap", slugs)

    def test_results_are_ranked_by_score_descending(self):
        request = RecommendationRequest(month=10, min_temp_c=20.0, max_cost_of_living=5)

        results = generate_recommendations(request, climate_provider=self.climate)

        scores = [r.score for r in results]
        self.assertEqual(scores, sorted(scores, reverse=True))
        # warm-cheap should outrank warm-expensive: cheaper and further above the temp floor.
        self.assertEqual(results[0].destination.slug, "warm-cheap")

    def test_destination_with_no_climate_data_is_skipped_gracefully(self):
        warm_cheap_climate = self.climate.get_monthly_climate(
            latitude=10.0, longitude=10.0, month=10
        )
        incomplete_climate = StubClimateProvider({(10.0, 10.0): warm_cheap_climate})
        request = RecommendationRequest(month=10)

        results = generate_recommendations(request, climate_provider=incomplete_climate)

        slugs = {r.destination.slug for r in results}
        self.assertEqual(slugs, {"warm-cheap"})

    def test_preference_fit_boosts_matching_trip_type(self):
        user = User.objects.create_user(email="traveler@example.com", password="testpass123")
        TravelerProfile.objects.create(user=user, preferred_trip_types=["city"])
        request = RecommendationRequest(month=10, user=user)

        results = generate_recommendations(request, climate_provider=self.climate)

        by_slug = {r.destination.slug: r for r in results}
        self.assertEqual(by_slug["warm-expensive"].preference_fit, 2.0)
        self.assertEqual(by_slug["warm-cheap"].preference_fit, 0.0)

    def test_repetition_penalty_lowers_score_for_completed_trips(self):
        user = User.objects.create_user(email="traveler@example.com", password="testpass123")
        Trip.objects.create(user=user, destination=self.warm_cheap, status="completed")
        request = RecommendationRequest(month=10, user=user)

        results = generate_recommendations(request, climate_provider=self.climate)

        by_slug = {r.destination.slug: r for r in results}
        self.assertEqual(by_slug["warm-cheap"].repetition_penalty, 3.0)
        self.assertEqual(by_slug["warm-expensive"].repetition_penalty, 0.0)

    def test_repetition_penalty_lowers_score_for_travel_history_entries(self):
        user = User.objects.create_user(email="traveler@example.com", password="testpass123")
        TravelHistoryEntry.objects.create(user=user, destination=self.warm_cheap, visited_year=2019)
        request = RecommendationRequest(month=10, user=user)

        results = generate_recommendations(request, climate_provider=self.climate)

        by_slug = {r.destination.slug: r for r in results}
        self.assertEqual(by_slug["warm-cheap"].repetition_penalty, 3.0)

    def test_anonymous_request_has_no_preference_or_repetition_effects(self):
        request = RecommendationRequest(month=10, user=None)

        results = generate_recommendations(request, climate_provider=self.climate)

        for result in results:
            self.assertEqual(result.preference_fit, 0.0)
            self.assertEqual(result.repetition_penalty, 0.0)


class SlowClimateProvider:
    """Simulates a real per-call network delay - lets a test exercise the
    request's climate-lookup time budget (2026-09-04 fix) without actually
    waiting anywhere close to a real HTTP timeout."""

    def __init__(self, climate, delay_seconds):
        self._climate = climate
        self._delay_seconds = delay_seconds

    def get_monthly_climate(self, *, latitude, longitude, month, year=None):
        time.sleep(self._delay_seconds)
        return self._climate


class ClimateLookupTimeBudgetTests(TestCase):
    """2026-09-04, real production timeout: a request naming no
    trip_type/max_cost_of_living (e.g. "montar um eurotrip de 5 dias")
    leaves the DB-level candidate set unfiltered, so a run of cold climate
    lookups across the full catalog could exceed gunicorn's worker
    timeout and kill the entire worker process. generate_recommendations
    now caps the climate-lookup loop's own wall-clock budget and returns
    whatever's already been scored instead."""

    def setUp(self):
        for i in range(5):
            _make_destination(f"dest-{i}", lat=float(i), lon=float(i))
        self.climate_summary = MonthlyClimateSummary(2025, 10, 25.0, 15.0, 5.0)

    @patch("recommendations.scoring.CLIMATE_LOOKUP_TIME_BUDGET_SECONDS", 0.05)
    def test_partial_results_returned_once_time_budget_is_exceeded(self):
        slow_climate = SlowClimateProvider(self.climate_summary, delay_seconds=0.03)
        request = RecommendationRequest(month=10)

        results = generate_recommendations(request, climate_provider=slow_climate)

        self.assertGreater(len(results), 0)
        self.assertLess(len(results), 5)

    def test_all_destinations_scored_when_well_within_budget(self):
        fast_climate = SlowClimateProvider(self.climate_summary, delay_seconds=0.0)
        request = RecommendationRequest(month=10)

        results = generate_recommendations(request, climate_provider=fast_climate)

        self.assertEqual(len(results), 5)
