import json
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from ai.orchestration import StreamingOrchestrationResult
from ai.views import RECOMMENDATIONS_DELIMITER
from analytics.models import Event
from recommendations.scoring import ScoredDestination
from travel.models import Destination
from users.models import User


class ChatPageTests(TestCase):
    def test_chat_page_renders_for_anonymous_users(self):
        response = self.client.get(reverse("ai:chat"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "message-input")
        self.assertContains(response, "chat-form")


class RecommendationsStreamViewTests(TestCase):
    def test_rejects_empty_message(self):
        response = self.client.post(reverse("ai:recommendations-api"), {"message": "   "})

        self.assertEqual(response.status_code, 400)

    def test_rejects_message_over_length_limit(self):
        response = self.client.post(
            reverse("ai:recommendations-api"), {"message": "x" * 2001}
        )

        self.assertEqual(response.status_code, 400)

    def test_rejects_get_requests(self):
        response = self.client.get(reverse("ai:recommendations-api"))

        self.assertEqual(response.status_code, 405)

    @patch("ai.views.stream_travel_recommendation")
    def test_streams_reply_chunks_for_anonymous_user(self, mock_stream):
        mock_stream.return_value = StreamingOrchestrationResult(
            recommendations=[],
            reply_chunks=iter(["Hello", " ", "traveler!"]),
        )

        response = self.client.post(
            reverse("ai:recommendations-api"), {"message": "somewhere warm"}
        )

        content = b"".join(response.streaming_content).decode()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(content, "Hello traveler!")
        mock_stream.assert_called_once()
        _, kwargs = mock_stream.call_args
        self.assertIsNone(kwargs["user"])

    @patch("ai.views.stream_travel_recommendation")
    def test_appends_recommendations_footer_when_present(self, mock_stream):
        destination = Destination.objects.create(
            slug="lisbon-pt",
            name="Lisbon",
            country="Portugal",
            latitude="38.72000",
            longitude="-9.14000",
            trip_type="city",
            cost_of_living=3,
            best_season="Mar-Oct",
            worst_season="Dec-Feb",
            short_description="A hilly coastal capital.",
            points_of_interest=[],
        )
        scored = ScoredDestination(
            destination=destination,
            avg_high_c=24.0,
            avg_low_c=16.0,
            preference_fit=0.0,
            budget_fit=0.0,
            temperature_fit=0.0,
            repetition_penalty=0.0,
            score=0.0,
        )
        mock_stream.return_value = StreamingOrchestrationResult(
            recommendations=[scored],
            reply_chunks=iter(["Try Lisbon!"]),
        )

        response = self.client.post(
            reverse("ai:recommendations-api"), {"message": "somewhere warm"}
        )

        content = b"".join(response.streaming_content).decode()
        text_part, _, json_part = content.partition(RECOMMENDATIONS_DELIMITER)
        self.assertEqual(text_part, "Try Lisbon!")
        parsed = json.loads(json_part)
        self.assertEqual(parsed, [{"slug": "lisbon-pt", "name": "Lisbon", "country": "Portugal"}])

    @patch("ai.views.stream_travel_recommendation")
    def test_passes_authenticated_user_through(self, mock_stream):
        mock_stream.return_value = StreamingOrchestrationResult(
            recommendations=[], reply_chunks=iter(["Hi!"])
        )
        user = User.objects.create_user(email="traveler@example.com", password="testpass123")
        self.client.force_login(user)

        self.client.post(reverse("ai:recommendations-api"), {"message": "somewhere warm"})

        _, kwargs = mock_stream.call_args
        self.assertEqual(kwargs["user"], user)

    @patch("ai.views.stream_travel_recommendation")
    def test_passes_a_stable_session_key_for_anonymous_users(self, mock_stream):
        mock_stream.return_value = StreamingOrchestrationResult(
            recommendations=[], reply_chunks=iter(["Hi!"])
        )

        self.client.post(reverse("ai:recommendations-api"), {"message": "hello"})

        _, kwargs = mock_stream.call_args
        self.assertTrue(kwargs["session_key"])
        self.assertEqual(kwargs["session_key"], self.client.session.session_key)


class RecommendationsStreamAnalyticsTests(TestCase):
    @patch("ai.views.stream_travel_recommendation")
    def test_any_message_records_travel_question_submitted(self, mock_stream):
        mock_stream.return_value = StreamingOrchestrationResult(
            recommendations=[], reply_chunks=iter(["Hi!"])
        )

        self.client.post(reverse("ai:recommendations-api"), {"message": "what's the weather?"})

        self.assertTrue(
            Event.objects.filter(event_type="travel_question_submitted").exists()
        )

    @patch("ai.views.stream_travel_recommendation")
    def test_anonymous_message_records_anonymized_ip_not_user(self, mock_stream):
        mock_stream.return_value = StreamingOrchestrationResult(
            recommendations=[], reply_chunks=iter(["Hi!"])
        )

        self.client.post(
            reverse("ai:recommendations-api"),
            {"message": "somewhere warm"},
            REMOTE_ADDR="203.0.113.42",
        )

        event = Event.objects.get(event_type="travel_question_submitted")
        self.assertIsNone(event.user)
        self.assertEqual(event.anonymized_ip, "203.0.113.0")

    @patch("ai.views.stream_travel_recommendation")
    def test_recommendations_present_records_recommendation_generated(self, mock_stream):
        destination = Destination.objects.create(
            slug="lisbon-pt",
            name="Lisbon",
            country="Portugal",
            latitude="38.72000",
            longitude="-9.14000",
            trip_type="city",
            cost_of_living=3,
            best_season="Mar-Oct",
            worst_season="Dec-Feb",
            short_description="A hilly coastal capital.",
            points_of_interest=[],
        )
        scored = ScoredDestination(
            destination=destination,
            avg_high_c=24.0,
            avg_low_c=16.0,
            preference_fit=0.0,
            budget_fit=0.0,
            temperature_fit=0.0,
            repetition_penalty=0.0,
            score=0.0,
        )
        mock_stream.return_value = StreamingOrchestrationResult(
            recommendations=[scored], reply_chunks=iter(["Try Lisbon!"])
        )

        self.client.post(reverse("ai:recommendations-api"), {"message": "somewhere warm"})

        self.assertTrue(
            Event.objects.filter(event_type="recommendation_generated").exists()
        )

    @patch("ai.views.stream_travel_recommendation")
    def test_no_recommendations_does_not_record_recommendation_generated(self, mock_stream):
        mock_stream.return_value = StreamingOrchestrationResult(
            recommendations=[], reply_chunks=iter(["Hi!"])
        )

        self.client.post(reverse("ai:recommendations-api"), {"message": "hello"})

        self.assertFalse(
            Event.objects.filter(event_type="recommendation_generated").exists()
        )
