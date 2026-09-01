import json
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from ai.models import SavedConversation
from ai.orchestration import FALLBACK_REPLY, StreamingOrchestrationResult
from ai.provider.base import AIResponse
from ai.views import CONVERSATION_DELIMITER, RECOMMENDATIONS_DELIMITER
from analytics.models import Event
from recommendations.scoring import ScoredDestination
from travel.models import Destination
from users.models import User


class StubSubjectProvider:
    """Minimal AIProvider stub for tests that exercise a NEW saved
    conversation being created (the only path that actually needs an AI
    call, for the conversation's subject/title) - see ai/conversations.py's
    record_turn docstring for why this needs to be stubbed explicitly
    rather than letting the view construct a real OpenAIProvider."""

    def __init__(self, subject="A trip idea"):
        self.subject = subject

    def generate_reply(self, messages, *, max_tokens=None):
        return AIResponse(content=self.subject, model="stub", prompt_tokens=0, completion_tokens=0)


class ChatPageTests(TestCase):
    def test_chat_page_renders_for_anonymous_users(self):
        response = self.client.get(reverse("ai:chat"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "message-input")
        self.assertContains(response, "chat-form")

    def test_login_prompt_modal_shown_to_anonymous_users(self):
        # 2026-09-02, direct request: a soft, dismissible nudge for
        # signed-out visitors - never a hard gate (chat still works fully
        # anonymously either way, per the "no account needed" landing
        # page promise).
        response = self.client.get(reverse("ai:chat"))

        self.assertContains(response, "<dialog")
        self.assertContains(response, "Continue without an account")

    def test_login_prompt_modal_not_shown_to_authenticated_users(self):
        # The #login-prompt-modal CSS *rule* itself is always present (it's
        # in the page's unconditional <style> block), and - since 2026-09-02
        # - authenticated users now render other <dialog> elements of their
        # own (the saved-conversation limit notices) too, so a bare "no
        # <dialog> tag at all" assertion is no longer meaningful here.
        # Assert on the login dialog's own opening tag (its quoted id
        # attribute, not the CSS selector spelling) and its content instead.
        user = User.objects.create_user(email="traveler@example.com", password="testpass123")
        self.client.force_login(user)

        response = self.client.get(reverse("ai:chat"))

        self.assertNotContains(response, 'id="login-prompt-modal"')
        self.assertNotContains(response, "Continue without an account")

    def test_saved_conversation_ui_shown_to_authenticated_users(self):
        # 2026-09-02, direct request: a ChatGPT-style sidebar (new
        # conversation, save checkbox, saved-conversation list) - saving is
        # a registered-users-only feature, so none of this UI exists for
        # anonymous visitors at all.
        user = User.objects.create_user(email="traveler@example.com", password="testpass123")
        self.client.force_login(user)

        response = self.client.get(reverse("ai:chat"))

        self.assertContains(response, 'id="chat-sidebar"')
        self.assertContains(response, 'id="new-conversation-btn"')
        self.assertContains(response, 'id="save-conversation-checkbox"')
        self.assertContains(response, 'id="conversation-limit-modal"')
        self.assertContains(response, 'id="conversation-size-limit-modal"')

    def test_saved_conversation_ui_not_shown_to_anonymous_users(self):
        response = self.client.get(reverse("ai:chat"))

        self.assertNotContains(response, 'id="chat-sidebar"')
        self.assertNotContains(response, 'id="new-conversation-btn"')
        self.assertNotContains(response, 'id="save-conversation-checkbox"')
        self.assertNotContains(response, 'id="conversation-limit-modal"')
        self.assertNotContains(response, 'id="conversation-size-limit-modal"')


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
        self.assertEqual(
            parsed,
            [
                {
                    "slug": "lisbon-pt",
                    "name": "Lisbon",
                    "country": "Portugal",
                    "trip_type": "City",
                    "cost_of_living": "Medium",
                    "avg_high_c": 24.0,
                    "fit_reasons": [],
                }
            ],
        )

    @patch("ai.views.stream_travel_recommendation")
    def test_recommendation_footer_translates_scoring_factors_into_fit_reasons(self, mock_stream):
        # 2026-09-01 UI/UX pass: the chat page's recommendation cards show
        # "why this fits you" - only ever derived from real scoring
        # factors already computed by recommendations.scoring, never
        # invented or exposing the AI's own reasoning.
        destination = Destination.objects.create(
            slug="bali-id",
            name="Bali",
            country="Indonesia",
            latitude="-8.34000",
            longitude="115.09000",
            trip_type="beach",
            cost_of_living=1,
            best_season="Apr-Oct",
            worst_season="Dec-Mar",
            short_description="A tropical island.",
            points_of_interest=[],
        )
        scored = ScoredDestination(
            destination=destination,
            avg_high_c=30.0,
            avg_low_c=24.0,
            preference_fit=2.0,
            budget_fit=1.5,
            temperature_fit=0.8,
            repetition_penalty=0.0,
            score=4.3,
        )
        mock_stream.return_value = StreamingOrchestrationResult(
            recommendations=[scored],
            reply_chunks=iter(["Try Bali!"]),
        )

        response = self.client.post(
            reverse("ai:recommendations-api"), {"message": "somewhere warm and cheap"}
        )

        content = b"".join(response.streaming_content).decode()
        _, _, json_part = content.partition(RECOMMENDATIONS_DELIMITER)
        parsed = json.loads(json_part)
        self.assertEqual(
            parsed[0]["fit_reasons"],
            ["Matches your travel style", "Within your budget", "Great climate match"],
        )

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


class SavedConversationStreamTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="traveler@example.com", password="testpass123")

    @patch("ai.conversations.get_ai_provider")
    @patch("ai.views.stream_travel_recommendation")
    def test_save_true_creates_a_new_conversation(self, mock_stream, mock_get_provider):
        mock_stream.return_value = StreamingOrchestrationResult(
            recommendations=[], reply_chunks=iter(["Here's an idea."])
        )
        mock_get_provider.return_value = StubSubjectProvider(subject="Warm getaway ideas")
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("ai:recommendations-api"), {"message": "somewhere warm", "save": "true"}
        )
        content = b"".join(response.streaming_content).decode()

        _, _, json_part = content.partition(CONVERSATION_DELIMITER)
        status = json.loads(json_part)
        self.assertTrue(status["saved"])
        self.assertEqual(status["subject"], "Warm getaway ideas")
        self.assertIsNone(status["reason"])
        conversation = SavedConversation.objects.get(pk=status["conversation_id"])
        self.assertEqual(conversation.user, self.user)
        self.assertEqual(len(conversation.messages), 2)

    @patch("ai.views.stream_travel_recommendation")
    def test_ai_provider_fallback_reply_is_not_saved(self, mock_stream):
        # 2026-09-02 review: a degraded FALLBACK_REPLY (the AI provider
        # was unreachable) used to be saved into SavedConversation exactly
        # like a real answer - permanently baking a transient outage
        # message into the traveler's history and counting toward their
        # char limit. It should be skipped entirely, same as save=false.
        mock_stream.return_value = StreamingOrchestrationResult(
            recommendations=[], reply_chunks=iter([FALLBACK_REPLY])
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("ai:recommendations-api"), {"message": "somewhere warm", "save": "true"}
        )
        content = b"".join(response.streaming_content).decode()

        _, _, json_part = content.partition(CONVERSATION_DELIMITER)
        status = json.loads(json_part)
        self.assertFalse(status["saved"])
        self.assertIsNone(status["reason"])
        self.assertEqual(SavedConversation.objects.count(), 0)

    @patch("ai.views.stream_travel_recommendation")
    def test_save_false_does_not_create_a_conversation(self, mock_stream):
        mock_stream.return_value = StreamingOrchestrationResult(
            recommendations=[], reply_chunks=iter(["Here's an idea."])
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("ai:recommendations-api"), {"message": "somewhere warm", "save": "false"}
        )
        content = b"".join(response.streaming_content).decode()

        _, _, json_part = content.partition(CONVERSATION_DELIMITER)
        status = json.loads(json_part)
        self.assertFalse(status["saved"])
        self.assertIsNone(status["reason"])
        self.assertEqual(SavedConversation.objects.count(), 0)

    @patch("ai.views.stream_travel_recommendation")
    def test_anonymous_user_never_gets_a_conversation_footer(self, mock_stream):
        mock_stream.return_value = StreamingOrchestrationResult(
            recommendations=[], reply_chunks=iter(["Here's an idea."])
        )

        response = self.client.post(
            reverse("ai:recommendations-api"), {"message": "somewhere warm", "save": "true"}
        )
        content = b"".join(response.streaming_content).decode()

        self.assertNotIn(CONVERSATION_DELIMITER, content)
        self.assertEqual(SavedConversation.objects.count(), 0)

    @patch("ai.conversations.get_ai_provider")
    @patch("ai.views.stream_travel_recommendation")
    def test_conversation_limit_reached_reports_reason_without_saving(
        self, mock_stream, mock_get_provider
    ):
        for _ in range(SavedConversation.MAX_CONVERSATIONS_PER_USER):
            SavedConversation.objects.create(user=self.user)
        mock_stream.return_value = StreamingOrchestrationResult(
            recommendations=[], reply_chunks=iter(["Here's an idea."])
        )
        mock_get_provider.return_value = StubSubjectProvider()
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("ai:recommendations-api"), {"message": "somewhere warm", "save": "true"}
        )
        content = b"".join(response.streaming_content).decode()

        _, _, json_part = content.partition(CONVERSATION_DELIMITER)
        status = json.loads(json_part)
        self.assertFalse(status["saved"])
        self.assertEqual(status["reason"], "conversation_limit_reached")
        self.assertEqual(
            SavedConversation.objects.count(), SavedConversation.MAX_CONVERSATIONS_PER_USER
        )

    @patch("ai.views.stream_travel_recommendation")
    def test_continues_an_existing_conversation_using_its_history(self, mock_stream):
        conversation = SavedConversation.objects.create(user=self.user, subject="Trip talk")
        conversation.messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        conversation.save()
        mock_stream.return_value = StreamingOrchestrationResult(
            recommendations=[], reply_chunks=iter(["Sure thing."])
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("ai:recommendations-api"),
            {
                "message": "tell me more",
                "save": "true",
                "conversation_id": str(conversation.pk),
            },
        )
        content = b"".join(response.streaming_content).decode()

        _, kwargs = mock_stream.call_args
        self.assertEqual(
            kwargs["history_override"],
            [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}],
        )
        _, _, json_part = content.partition(CONVERSATION_DELIMITER)
        status = json.loads(json_part)
        self.assertTrue(status["saved"])
        self.assertEqual(status["conversation_id"], conversation.pk)
        # An already-titled conversation doesn't get its subject
        # regenerated on every later turn.
        self.assertIsNone(status["subject"])
        conversation.refresh_from_db()
        self.assertEqual(len(conversation.messages), 4)


class ConversationEndpointsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="traveler@example.com", password="testpass123")
        self.other_user = User.objects.create_user(
            email="other@example.com", password="testpass123"
        )

    def test_list_requires_login(self):
        response = self.client.get(reverse("ai:conversation-list"))

        self.assertEqual(response.status_code, 403)

    def test_list_returns_only_the_callers_own_conversations(self):
        SavedConversation.objects.create(user=self.user, subject="Mine")
        SavedConversation.objects.create(user=self.other_user, subject="Not mine")
        self.client.force_login(self.user)

        response = self.client.get(reverse("ai:conversation-list"))
        data = response.json()

        self.assertEqual(len(data["conversations"]), 1)
        self.assertEqual(data["conversations"][0]["subject"], "Mine")
        self.assertEqual(data["max_conversations"], SavedConversation.MAX_CONVERSATIONS_PER_USER)

    def test_detail_requires_login(self):
        conversation = SavedConversation.objects.create(user=self.user)

        response = self.client.get(reverse("ai:conversation-detail", args=[conversation.pk]))

        self.assertEqual(response.status_code, 403)

    def test_detail_returns_the_stored_messages(self):
        conversation = SavedConversation.objects.create(user=self.user, subject="Trip talk")
        conversation.messages = [{"role": "user", "content": "hi"}]
        conversation.save()
        self.client.force_login(self.user)

        response = self.client.get(reverse("ai:conversation-detail", args=[conversation.pk]))
        data = response.json()

        self.assertEqual(data["subject"], "Trip talk")
        self.assertEqual(data["messages"], [{"role": "user", "content": "hi"}])

    def test_detail_404s_for_another_users_conversation(self):
        conversation = SavedConversation.objects.create(user=self.other_user)
        self.client.force_login(self.user)

        response = self.client.get(reverse("ai:conversation-detail", args=[conversation.pk]))

        self.assertEqual(response.status_code, 404)

    def test_delete_removes_the_conversation(self):
        conversation = SavedConversation.objects.create(user=self.user)
        self.client.force_login(self.user)

        response = self.client.post(reverse("ai:conversation-delete", args=[conversation.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(SavedConversation.objects.filter(pk=conversation.pk).exists())

    def test_delete_404s_for_another_users_conversation(self):
        conversation = SavedConversation.objects.create(user=self.other_user)
        self.client.force_login(self.user)

        response = self.client.post(reverse("ai:conversation-delete", args=[conversation.pk]))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(SavedConversation.objects.filter(pk=conversation.pk).exists())

    def test_reset_clears_memory_for_authenticated_user(self):
        from ai import memory

        key = memory.conversation_key(user=self.user, session_key=None)
        memory.append_turn(key, user_message="hi", assistant_reply="hello")
        self.client.force_login(self.user)

        response = self.client.post(reverse("ai:conversation-reset"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(memory.get_history(key), [])

    def test_reset_works_for_anonymous_users_too(self):
        response = self.client.post(reverse("ai:conversation-reset"))

        self.assertEqual(response.status_code, 200)
