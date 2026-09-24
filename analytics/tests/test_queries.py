"""Correctness tests for analytics/queries.py - runs against the real
warehouse views, same approach as analytics/warehouse/tests/test_views.py,
not mocks."""

import datetime

from django.test import TestCase
from django.utils import timezone

from analytics.models import Event
from analytics.queries import (
    accommodation_click_through_rate_by_destination,
    acquisition_by_traveler_preference,
    acquisition_funnel,
    top_clicked_destinations,
    top_destinations_by_traveler_trip_type,
)
from travel.models import Destination
from users.models import TravelerProfile, User


def _make_destination(slug, **overrides):
    defaults = {
        "name": slug,
        "country": "Testland",
        "latitude": "1.00000",
        "longitude": "1.00000",
        "trip_type": "beach",
        "cost_of_living": 2,
        "best_season": "Jan-Dec",
        "worst_season": "None",
        "short_description": "A test destination.",
        "points_of_interest": [],
    }
    defaults.update(overrides)
    return Destination.objects.create(slug=slug, **defaults)


def _event_at(event_type, *, offset_minutes, base, **kwargs):
    event = Event.objects.create(event_type=event_type, **kwargs)
    Event.objects.filter(pk=event.pk).update(
        created_at=base + datetime.timedelta(minutes=offset_minutes)
    )
    return event


class TopClickedDestinationsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="traveler@example.com", password="x")
        self.key = f"chat-history:user:{self.user.pk}"
        self.base = timezone.now() - datetime.timedelta(hours=1)
        _make_destination("bali-id")
        _make_destination("lisbon-pt")

    def test_ranks_by_click_count_and_excludes_zero_click_destinations(self):
        _event_at(
            "recommendation_generated",
            offset_minutes=0,
            base=self.base,
            user=self.user,
            conversation_key=self.key,
            metadata={"destination_slugs": ["bali-id", "lisbon-pt"]},
        )
        _event_at(
            "accommodation_outbound_click",
            offset_minutes=1,
            base=self.base,
            user=self.user,
            conversation_key=self.key,
            metadata={"destination_slug": "bali-id"},
        )

        today = timezone.now().date()
        results = list(
            top_clicked_destinations(
                start_date=today - datetime.timedelta(days=1), end_date=today
            )
        )

        slugs = [r["destination_slug"] for r in results]
        self.assertIn("bali-id", slugs)
        self.assertNotIn("lisbon-pt", slugs)


class ClickThroughRateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="traveler@example.com", password="x")
        self.key = f"chat-history:user:{self.user.pk}"
        self.base = timezone.now() - datetime.timedelta(hours=1)
        _make_destination("bali-id")

    def test_computes_impressions_and_clicks(self):
        _event_at(
            "recommendation_generated",
            offset_minutes=0,
            base=self.base,
            user=self.user,
            conversation_key=self.key,
            metadata={"destination_slugs": ["bali-id"]},
        )
        _event_at(
            "accommodation_outbound_click",
            offset_minutes=1,
            base=self.base,
            user=self.user,
            conversation_key=self.key,
            metadata={"destination_slug": "bali-id"},
        )

        today = timezone.now().date()
        rows = list(
            accommodation_click_through_rate_by_destination(
                start_date=today - datetime.timedelta(days=1), end_date=today
            )
        )

        row = next(r for r in rows if r["destination_slug"] == "bali-id")
        self.assertEqual(row["impressions"], 1)
        self.assertEqual(row["clicks"], 1)

    def test_min_impressions_filters_out_low_exposure_destinations(self):
        _event_at(
            "recommendation_generated",
            offset_minutes=0,
            base=self.base,
            user=self.user,
            conversation_key=self.key,
            metadata={"destination_slugs": ["bali-id"]},
        )

        today = timezone.now().date()
        rows = list(
            accommodation_click_through_rate_by_destination(
                start_date=today - datetime.timedelta(days=1),
                end_date=today,
                min_impressions=5,
            )
        )

        self.assertEqual(list(rows), [])


class TopDestinationsByTravelerTripTypeTests(TestCase):
    def setUp(self):
        _make_destination("bali-id")
        self.user = User.objects.create_user(email="traveler@example.com", password="x")
        TravelerProfile.objects.create(user=self.user, preferred_trip_types=["beach"])

    def test_matches_clicks_from_travelers_with_the_given_preference(self):
        Event.objects.create(
            event_type="accommodation_outbound_click",
            user=self.user,
            metadata={
                "destination_slug": "bali-id",
                "traveler_preferred_trip_types": ["beach"],
            },
        )
        Event.objects.create(
            event_type="accommodation_outbound_click",
            anonymized_ip="203.0.113.0",
            metadata={"destination_slug": "bali-id"},
        )

        today = timezone.now().date()
        results = list(
            top_destinations_by_traveler_trip_type(
                trip_type="beach",
                start_date=today - datetime.timedelta(days=1),
                end_date=today,
            )
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["metadata__destination_slug"], "bali-id")
        self.assertEqual(results[0]["clicks"], 1)


class AcquisitionFunnelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="traveler@example.com", password="x")
        self.key = f"chat-history:user:{self.user.pk}"
        self.base = timezone.now() - datetime.timedelta(hours=1)

    def test_groups_by_source_medium_campaign_content_with_correct_counts(self):
        _event_at(
            "acquisition_captured",
            offset_minutes=0,
            base=self.base,
            user=self.user,
            conversation_key=self.key,
            metadata={
                "touch_type": "first",
                "source": "tiktok",
                "medium": "organic_social",
                "campaign": "warm_november",
                "content": "video1",
                "term": None,
            },
        )
        _event_at(
            "travel_question_submitted",
            offset_minutes=1,
            base=self.base,
            user=self.user,
            conversation_key=self.key,
        )
        _event_at(
            "recommendation_generated",
            offset_minutes=2,
            base=self.base,
            user=self.user,
            conversation_key=self.key,
            metadata={"destination_slugs": []},
        )

        today = timezone.now().date()
        rows = list(
            acquisition_funnel(start_date=today - datetime.timedelta(days=1), end_date=today)
        )

        row = next(r for r in rows if r["source"] == "tiktok")
        self.assertEqual(row["medium"], "organic_social")
        self.assertEqual(row["campaign"], "warm_november")
        self.assertEqual(row["sessions"], 1)
        self.assertEqual(row["planning_starts"], 1)
        self.assertEqual(row["recommendations"], 1)
        self.assertEqual(row["accommodation_clicks"], 0)

    def test_touch_type_filters_first_vs_latest(self):
        _event_at(
            "acquisition_captured",
            offset_minutes=0,
            base=self.base,
            user=self.user,
            conversation_key=self.key,
            metadata={"touch_type": "first", "source": "tiktok", "medium": "organic_social"},
        )
        _event_at(
            "acquisition_captured",
            offset_minutes=5,
            base=self.base,
            user=self.user,
            conversation_key=self.key,
            metadata={"touch_type": "latest", "source": "google", "medium": "organic_search"},
        )

        today = timezone.now().date()
        first_rows = list(
            acquisition_funnel(
                start_date=today - datetime.timedelta(days=1), end_date=today, touch_type="first"
            )
        )
        latest_rows = list(
            acquisition_funnel(
                start_date=today - datetime.timedelta(days=1), end_date=today, touch_type="latest"
            )
        )

        self.assertEqual([r["source"] for r in first_rows], ["tiktok"])
        self.assertEqual([r["source"] for r in latest_rows], ["google"])


class AcquisitionByTravelerPreferenceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="traveler@example.com", password="x")

    def test_filters_by_cost_of_living_and_groups_by_source(self):
        Event.objects.create(
            event_type="accommodation_outbound_click",
            user=self.user,
            metadata={
                "traveler_preferred_cost_of_living": 2,
                "acquisition": {
                    "first_touch": {"source": "tiktok", "campaign": "budget_trips", "content": None}
                },
            },
        )
        Event.objects.create(
            event_type="accommodation_outbound_click",
            user=self.user,
            metadata={"traveler_preferred_cost_of_living": 5},
        )

        today = timezone.now().date()
        results = list(
            acquisition_by_traveler_preference(
                start_date=today - datetime.timedelta(days=1),
                end_date=today,
                cost_of_living=2,
            )
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["metadata__acquisition__first_touch__source"], "tiktok")
        self.assertEqual(results[0]["clicks"], 1)

    def test_filters_by_trip_type(self):
        Event.objects.create(
            event_type="accommodation_outbound_click",
            user=self.user,
            metadata={
                "traveler_preferred_trip_types": ["beach"],
                "acquisition": {"first_touch": {"source": "instagram"}},
            },
        )

        today = timezone.now().date()
        results = list(
            acquisition_by_traveler_preference(
                start_date=today - datetime.timedelta(days=1),
                end_date=today,
                trip_type="beach",
            )
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["metadata__acquisition__first_touch__source"], "instagram")

    def test_requires_at_least_one_dimension(self):
        today = timezone.now().date()

        with self.assertRaises(ValueError):
            list(acquisition_by_traveler_preference(start_date=today, end_date=today))
