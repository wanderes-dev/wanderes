import datetime

from django.test import TestCase
from django.utils import timezone

from analytics.models import DailyProductMetrics, Event
from analytics.tasks import refresh_daily_metrics
from users.models import User


class RefreshDailyMetricsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="traveler@example.com", password="x")
        self.today = timezone.now().date()

    def _event_today(self, event_type, **kwargs):
        event = Event.objects.create(event_type=event_type, **kwargs)
        Event.objects.filter(pk=event.pk).update(
            created_at=timezone.now().replace(hour=10, minute=0, second=0, microsecond=0)
        )
        return event

    def test_creates_a_row_for_the_target_date(self):
        refresh_daily_metrics(target_date=self.today)

        self.assertTrue(DailyProductMetrics.objects.filter(date=self.today).exists())

    def test_counts_conversations_and_messages(self):
        key = f"chat-history:user:{self.user.pk}"
        self._event_today(
            "travel_question_submitted", user=self.user, conversation_key=key, locale="en"
        )

        refresh_daily_metrics(target_date=self.today)

        row = DailyProductMetrics.objects.get(date=self.today)
        self.assertEqual(row.conversations_started, 1)
        self.assertEqual(row.messages_sent, 1)

    def test_counts_ai_failures_and_computes_latency_percentiles(self):
        self._event_today(
            "llm_request_completed",
            metadata={"operation": "extract_intent", "success": True, "latency_ms": 100.0},
        )
        self._event_today(
            "llm_request_completed",
            metadata={
                "operation": "stream_reply",
                "success": False,
                "latency_ms": 200.0,
                "error_type": "AIProviderError",
            },
        )

        refresh_daily_metrics(target_date=self.today)

        row = DailyProductMetrics.objects.get(date=self.today)
        self.assertEqual(row.ai_requests_total, 2)
        self.assertEqual(row.ai_requests_failed, 1)
        self.assertIsNotNone(row.ai_latency_p50_ms)

    def test_rerunning_for_the_same_date_does_not_double_count(self):
        # Idempotent by design - a scheduled batch job with retry
        # configured must be safe to run twice for the same date.
        self._event_today("user_registered", user=self.user)

        refresh_daily_metrics(target_date=self.today)
        refresh_daily_metrics(target_date=self.today)

        self.assertEqual(DailyProductMetrics.objects.filter(date=self.today).count(), 1)
        row = DailyProductMetrics.objects.get(date=self.today)
        self.assertEqual(row.signups_completed, 1)

    def test_events_outside_the_target_date_are_not_counted(self):
        key = f"chat-history:user:{self.user.pk}"
        event = Event.objects.create(
            event_type="travel_question_submitted", user=self.user, conversation_key=key
        )
        Event.objects.filter(pk=event.pk).update(
            created_at=timezone.now() - datetime.timedelta(days=5)
        )

        refresh_daily_metrics(target_date=self.today)

        row = DailyProductMetrics.objects.get(date=self.today)
        self.assertEqual(row.conversations_started, 0)

    def test_defaults_to_yesterday_when_no_date_given(self):
        yesterday = self.today - datetime.timedelta(days=1)
        key = f"chat-history:user:{self.user.pk}"
        event = Event.objects.create(
            event_type="travel_question_submitted", user=self.user, conversation_key=key
        )
        Event.objects.filter(pk=event.pk).update(
            created_at=timezone.now() - datetime.timedelta(days=1)
        )

        refresh_daily_metrics()

        row = DailyProductMetrics.objects.get(date=yesterday)
        self.assertEqual(row.conversations_started, 1)
