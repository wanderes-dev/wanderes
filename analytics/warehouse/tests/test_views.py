"""Data-quality and correctness tests for the warehouse views - these
query the real Postgres views (created by
analytics/migrations/0003_create_warehouse_views.py), not mocks, so a real
SQL regression in any view actually fails these.

Event.created_at uses auto_now_add=True, which silently ignores any
explicit value passed to .objects.create() - every fixture below creates
the row first, then uses a bare .update() (bypasses auto_now_add, unlike
.save()) to set the timestamp a test actually needs. Worth remembering so
a future test here doesn't trip over the same thing."""

import datetime

from django.test import TestCase
from django.utils import timezone

from analytics.models import Event
from analytics.warehouse.models import (
    DimDestination,
    FactAiRequest,
    FactConversation,
    FactFeedback,
    FactRecommendation,
)
from travel.models import Destination
from trips.models import Feedback, Trip
from users.models import User


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


class EpisodeSplittingTests(TestCase):
    """The most important correctness fix in this warehouse:
    ai.memory.conversation_key() alone is NOT a per-conversation identifier
    for an authenticated user (same string across their entire chat
    history) - int_event_episodes has to split it into real episodes on a
    30-minute inactivity gap, or every fact table built on top would
    silently merge unrelated visits together."""

    def setUp(self):
        self.user = User.objects.create_user(email="traveler@example.com", password="x")
        self.key = f"chat-history:user:{self.user.pk}"
        self.base = timezone.now() - datetime.timedelta(hours=3)

    def test_events_40_minutes_apart_get_different_episode_numbers(self):
        _event_at(
            "travel_question_submitted",
            offset_minutes=0,
            base=self.base,
            user=self.user,
            conversation_key=self.key,
        )
        _event_at(
            "travel_question_submitted",
            offset_minutes=40,
            base=self.base,
            user=self.user,
            conversation_key=self.key,
        )

        episodes = list(
            FactConversation.objects.filter(conversation_key=self.key).order_by("episode_number")
        )
        self.assertEqual(len(episodes), 2)
        self.assertEqual(episodes[0].episode_number, 1)
        self.assertEqual(episodes[1].episode_number, 2)
        self.assertEqual(episodes[0].message_count, 1)
        self.assertEqual(episodes[1].message_count, 1)

    def test_events_10_minutes_apart_stay_in_the_same_episode(self):
        _event_at(
            "travel_question_submitted",
            offset_minutes=0,
            base=self.base,
            user=self.user,
            conversation_key=self.key,
        )
        _event_at(
            "travel_question_submitted",
            offset_minutes=10,
            base=self.base,
            user=self.user,
            conversation_key=self.key,
        )

        episodes = list(FactConversation.objects.filter(conversation_key=self.key))
        self.assertEqual(len(episodes), 1)
        self.assertEqual(episodes[0].message_count, 2)

    def test_message_count_ignores_non_message_event_types(self):
        # recommendation_generated/destination_selected shouldn't inflate
        # "how many messages did the traveler send."
        _event_at(
            "travel_question_submitted",
            offset_minutes=0,
            base=self.base,
            user=self.user,
            conversation_key=self.key,
        )
        _event_at(
            "recommendation_generated",
            offset_minutes=1,
            base=self.base,
            user=self.user,
            conversation_key=self.key,
            metadata={"destination_slugs": []},
        )

        episode = FactConversation.objects.get(conversation_key=self.key)
        self.assertEqual(episode.message_count, 1)
        self.assertTrue(episode.reached_recommendation)


class FactRecommendationsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="traveler@example.com", password="x")
        self.key = f"chat-history:user:{self.user.pk}"
        self.base = timezone.now() - datetime.timedelta(hours=1)
        _make_destination("bali-id")
        _make_destination("lisbon-pt")

    def test_selected_and_saved_are_computed_correctly(self):
        _event_at(
            "recommendation_generated",
            offset_minutes=0,
            base=self.base,
            user=self.user,
            conversation_key=self.key,
            metadata={"destination_slugs": ["bali-id", "lisbon-pt"]},
        )
        _event_at(
            "destination_selected",
            offset_minutes=1,
            base=self.base,
            user=self.user,
            conversation_key=self.key,
            metadata={"destination_slug": "bali-id"},
        )
        _event_at(
            "trip_created",
            offset_minutes=2,
            base=self.base,
            user=self.user,
            conversation_key=self.key,
            metadata={"destination_slug": "bali-id", "source": "chat_recommendation"},
        )

        bali = FactRecommendation.objects.get(conversation_key=self.key, destination_slug="bali-id")
        lisbon = FactRecommendation.objects.get(
            conversation_key=self.key, destination_slug="lisbon-pt"
        )
        self.assertTrue(bali.was_selected)
        self.assertTrue(bali.was_saved)
        self.assertFalse(lisbon.was_selected)
        self.assertFalse(lisbon.was_saved)

    def test_a_selection_before_the_recommendation_does_not_count(self):
        # Correlation only looks forward within the same episode - an
        # earlier, unrelated destination_selected for the same slug must
        # not get misattributed to this recommendation.
        _event_at(
            "destination_selected",
            offset_minutes=0,
            base=self.base,
            user=self.user,
            conversation_key=self.key,
            metadata={"destination_slug": "bali-id"},
        )
        _event_at(
            "recommendation_generated",
            offset_minutes=1,
            base=self.base,
            user=self.user,
            conversation_key=self.key,
            metadata={"destination_slugs": ["bali-id"]},
        )

        rec = FactRecommendation.objects.get(conversation_key=self.key, destination_slug="bali-id")
        self.assertFalse(rec.was_selected)


class DimDestinationsTests(TestCase):
    def test_has_video_reflects_country_entry_requirement(self):
        from travel.models import CountryEntryRequirement

        _make_destination("with-video-dest", country="Videoland")
        _make_destination("without-video-dest", country="Novideoland")
        CountryEntryRequirement.objects.create(
            country="Videoland", videos=[["https://youtube.com/watch?v=abc", "EN"]]
        )
        CountryEntryRequirement.objects.create(country="Novideoland", videos=[])

        self.assertTrue(DimDestination.objects.get(slug="with-video-dest").has_video)
        self.assertFalse(DimDestination.objects.get(slug="without-video-dest").has_video)

    def test_has_video_is_false_with_no_entry_requirement_row_at_all(self):
        _make_destination("no-requirements-dest", country="Nowhereland")

        self.assertFalse(DimDestination.objects.get(slug="no-requirements-dest").has_video)


class FactFeedbackTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="traveler@example.com", password="x")
        self.destination = _make_destination("lisbon-pt")

    def test_resolves_destination_directly_when_set(self):
        Feedback.objects.create(user=self.user, destination=self.destination, rating=9, tags=[])

        row = FactFeedback.objects.get(user_id=self.user.pk)
        self.assertEqual(row.destination_slug, "lisbon-pt")

    def test_resolves_destination_via_trip_when_feedback_destination_is_null(self):
        trip = Trip.objects.create(user=self.user, destination=self.destination, status="completed")
        Feedback.objects.create(user=self.user, trip=trip, rating=7, tags=[])

        row = FactFeedback.objects.get(user_id=self.user.pk)
        self.assertEqual(row.destination_slug, "lisbon-pt")


class FactAiRequestsTests(TestCase):
    def test_operational_events_have_no_user_or_conversation_key(self):
        Event.objects.create(
            event_type="llm_request_completed",
            metadata={"operation": "extract_intent", "success": True, "latency_ms": 120.5},
        )

        row = FactAiRequest.objects.get()
        self.assertIsNone(row.conversation_key)
        self.assertTrue(row.success)
        self.assertGreaterEqual(row.latency_ms, 0)

    def test_latency_is_never_negative(self):
        # Data-quality invariant, not just a happy-path check - a future
        # bug computing a negative duration would get caught here instead
        # of silently poisoning a p50/p95/p99 query.
        Event.objects.create(
            event_type="provider_request_completed",
            metadata={
                "operation": "open_meteo_monthly_climate",
                "success": False,
                "latency_ms": 5.0,
            },
        )

        self.assertTrue(all(r.latency_ms >= 0 for r in FactAiRequest.objects.all()))

    def test_only_the_two_operational_event_types_appear(self):
        Event.objects.create(event_type="user_registered")
        Event.objects.create(
            event_type="llm_request_completed",
            metadata={"operation": "extract_intent", "success": True, "latency_ms": 1.0},
        )

        event_types = set(FactAiRequest.objects.values_list("event_type", flat=True))
        self.assertEqual(event_types, {"llm_request_completed"})
