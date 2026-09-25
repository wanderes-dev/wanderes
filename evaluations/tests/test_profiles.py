from django.test import TestCase

from evaluations.profiles import synthetic_traveler
from travel.models import Destination
from trips.models import TravelHistoryEntry, Trip
from users.models import TravelerProfile, User


class SyntheticTravelerTests(TestCase):
    def test_no_overrides_yields_anonymous(self):
        with synthetic_traveler("T-1", None) as user:
            self.assertIsNone(user)

    def test_empty_overrides_yields_anonymous(self):
        with synthetic_traveler("T-1", {}) as user:
            self.assertIsNone(user)

    def test_profile_fields_are_set(self):
        with synthetic_traveler(
            "T-1", {"preferred_trip_types": ["beach"], "home_country": "Brazil"}
        ) as user:
            self.assertIsNotNone(user)
            profile = TravelerProfile.objects.get(user=user)
            self.assertEqual(profile.preferred_trip_types, ["beach"])
            self.assertEqual(profile.home_country, "Brazil")

    def test_completed_trip_slugs_create_trips(self):
        destination = Destination.objects.create(
            slug="test-dest",
            name="Test",
            country="Testland",
            latitude=1.0,
            longitude=1.0,
            trip_type="beach",
            cost_of_living=1,
            best_season="x",
            worst_season="x",
            short_description="x",
            points_of_interest=[],
        )
        with synthetic_traveler("T-1", {"completed_trip_slugs": ["test-dest"]}) as user:
            trips = Trip.objects.filter(user=user, status="completed")
            self.assertEqual(trips.count(), 1)
            self.assertEqual(trips.first().destination, destination)

    def test_travel_history_slugs_create_entries(self):
        Destination.objects.create(
            slug="test-dest-2",
            name="Test",
            country="Testland",
            latitude=1.0,
            longitude=1.0,
            trip_type="beach",
            cost_of_living=1,
            best_season="x",
            worst_season="x",
            short_description="x",
            points_of_interest=[],
        )
        with synthetic_traveler("T-1", {"travel_history_slugs": ["test-dest-2"]}) as user:
            self.assertEqual(TravelHistoryEntry.objects.filter(user=user).count(), 1)

    def test_unknown_slug_is_silently_skipped_not_an_error(self):
        with synthetic_traveler("T-1", {"completed_trip_slugs": ["does-not-exist"]}) as user:
            self.assertEqual(Trip.objects.filter(user=user).count(), 0)

    def test_user_is_deleted_after_the_context_exits(self):
        email = "eval-synthetic-t-1@example.invalid"
        with synthetic_traveler("T-1", {"home_country": "Brazil"}):
            self.assertTrue(User.objects.filter(email=email).exists())
        self.assertFalse(User.objects.filter(email=email).exists())

    def test_user_is_deleted_even_if_the_block_raises(self):
        email = "eval-synthetic-t-2@example.invalid"
        with self.assertRaises(RuntimeError):
            with synthetic_traveler("T-2", {"home_country": "Brazil"}):
                raise RuntimeError("boom")
        self.assertFalse(User.objects.filter(email=email).exists())
