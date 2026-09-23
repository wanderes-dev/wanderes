"""Correctness tests for analytics/queries.py - runs against the real
warehouse views, same approach as analytics/warehouse/tests/test_views.py,
not mocks."""

import datetime

from django.test import TestCase
from django.utils import timezone

from analytics.models import Event
from analytics.queries import (
    accommodation_click_through_rate_by_destination,
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
