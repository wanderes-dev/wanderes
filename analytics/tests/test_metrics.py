from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from analytics import metrics
from analytics.models import Event
from users.models import User


def _make_event(event_type, user, days_ago):
    event = Event.objects.create(event_type=event_type, user=user)
    Event.objects.filter(pk=event.pk).update(
        created_at=timezone.now() - timedelta(days=days_ago)
    )
    return event


class ActiveUserMetricsTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(email="alice@example.com", password="testpass123")
        self.bob = User.objects.create_user(email="bob@example.com", password="testpass123")

    def test_dau_counts_only_todays_chat_interactions(self):
        _make_event("travel_question_submitted", self.alice, days_ago=0)
        _make_event("travel_question_submitted", self.bob, days_ago=5)

        self.assertEqual(metrics.dau(), 1)

    def test_wau_counts_last_7_days(self):
        _make_event("travel_question_submitted", self.alice, days_ago=1)
        _make_event("travel_question_submitted", self.bob, days_ago=6)

        self.assertEqual(metrics.wau(), 2)

    def test_mau_counts_last_30_days(self):
        _make_event("travel_question_submitted", self.alice, days_ago=29)
        _make_event("travel_question_submitted", self.bob, days_ago=31)

        self.assertEqual(metrics.mau(), 1)

    def test_same_user_multiple_events_counts_once(self):
        _make_event("travel_question_submitted", self.alice, days_ago=0)
        _make_event("travel_question_submitted", self.alice, days_ago=1)

        self.assertEqual(metrics.wau(), 1)

    def test_anonymous_events_never_count(self):
        Event.objects.create(event_type="travel_question_submitted", anonymized_ip="1.2.3.0")

        self.assertEqual(metrics.dau(), 0)

    def test_non_chat_events_do_not_make_a_user_active(self):
        _make_event("trip_created", self.alice, days_ago=0)

        self.assertEqual(metrics.dau(), 0)


class PerActiveUserMetricsTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(email="alice@example.com", password="testpass123")
        _make_event("travel_question_submitted", self.alice, days_ago=1)

    def test_recommendations_per_active_user(self):
        _make_event("recommendation_generated", self.alice, days_ago=1)
        _make_event("recommendation_generated", self.alice, days_ago=1)

        self.assertEqual(metrics.recommendations_per_active_user(), 2.0)

    def test_trips_per_active_user(self):
        _make_event("trip_created", self.alice, days_ago=1)

        self.assertEqual(metrics.trips_per_active_user(), 1.0)

    def test_feedback_rate(self):
        _make_event("feedback_submitted", self.alice, days_ago=1)

        self.assertEqual(metrics.feedback_rate(), 1.0)

    def test_returns_none_when_no_active_users(self):
        self.assertIsNone(metrics.trips_per_active_user(window_days=0))


class RetentionRateTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(email="alice@example.com", password="testpass123")
        self.bob = User.objects.create_user(email="bob@example.com", password="testpass123")

    def test_returns_none_for_a_day_with_no_activity(self):
        reference_date = (timezone.now() - timedelta(days=10)).date()

        self.assertIsNone(metrics.retention_rate(reference_date))

    def test_computes_fraction_who_returned(self):
        reference_date = (timezone.now() - timedelta(days=10)).date()
        _make_event("travel_question_submitted", self.alice, days_ago=10)
        _make_event("travel_question_submitted", self.bob, days_ago=10)
        # Only alice comes back within the following 7 days.
        _make_event("travel_question_submitted", self.alice, days_ago=8)

        self.assertEqual(metrics.retention_rate(reference_date, window_days=7), 0.5)

    def test_no_returning_users_gives_zero(self):
        reference_date = (timezone.now() - timedelta(days=10)).date()
        _make_event("travel_question_submitted", self.alice, days_ago=10)

        self.assertEqual(metrics.retention_rate(reference_date, window_days=7), 0.0)
