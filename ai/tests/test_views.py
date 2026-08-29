from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from ai.orchestration import StreamingOrchestrationResult
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
            needs_clarification=False,
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
    def test_passes_authenticated_user_through(self, mock_stream):
        mock_stream.return_value = StreamingOrchestrationResult(
            needs_clarification=False, recommendations=[], reply_chunks=iter(["Hi!"])
        )
        user = User.objects.create_user(email="traveler@example.com", password="testpass123")
        self.client.force_login(user)

        self.client.post(reverse("ai:recommendations-api"), {"message": "somewhere warm"})

        _, kwargs = mock_stream.call_args
        self.assertEqual(kwargs["user"], user)
