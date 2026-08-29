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


def _make_destination(slug, *, lat, lon, trip_type="beach", cost_of_living=3):
    return Destination.objects.create(
        slug=slug,
        name=slug,
        country="Testland",
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
