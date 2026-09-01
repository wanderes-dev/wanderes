from django.test import TestCase

from ai.conversations import (
    REASON_CONVERSATION_LIMIT_REACHED,
    REASON_SIZE_LIMIT_EXCEEDED,
    record_turn,
)
from ai.models import SavedConversation
from ai.provider.base import AIProviderError, AIResponse
from users.models import User


class StubAIProvider:
    def __init__(self, *, subject="A trip to somewhere", fail=False):
        self.subject = subject
        self.fail = fail
        self.generate_reply_calls = []

    def generate_reply(self, messages, *, max_tokens=None):
        self.generate_reply_calls.append(messages)
        if self.fail:
            raise AIProviderError("boom")
        return AIResponse(
            content=self.subject, model="stub", prompt_tokens=0, completion_tokens=0
        )


class RecordTurnTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="traveler@example.com", password="testpass123")

    def test_bypassed_when_save_not_requested(self):
        result = record_turn(
            user=self.user,
            conversation=None,
            save_requested=False,
            user_message="hi",
            assistant_reply="hello",
        )

        self.assertFalse(result.saved)
        self.assertEqual(SavedConversation.objects.count(), 0)

    def test_bypassed_for_anonymous_user(self):
        result = record_turn(
            user=None,
            conversation=None,
            save_requested=True,
            user_message="hi",
            assistant_reply="hello",
            ai_provider=StubAIProvider(),
        )

        self.assertFalse(result.saved)
        self.assertEqual(SavedConversation.objects.count(), 0)

    def test_creates_new_conversation_and_generates_subject(self):
        provider = StubAIProvider(subject="Beach trip planning")

        result = record_turn(
            user=self.user,
            conversation=None,
            save_requested=True,
            user_message="somewhere warm",
            assistant_reply="Here are some ideas",
            ai_provider=provider,
        )

        self.assertTrue(result.saved)
        self.assertIsNone(result.reason)
        self.assertEqual(result.subject, "Beach trip planning")
        conversation = SavedConversation.objects.get(pk=result.conversation_id)
        self.assertEqual(conversation.subject, "Beach trip planning")
        self.assertEqual(
            conversation.messages,
            [
                {"role": "user", "content": "somewhere warm"},
                {"role": "assistant", "content": "Here are some ideas"},
            ],
        )
        self.assertEqual(len(provider.generate_reply_calls), 1)

    def test_continues_existing_conversation_without_regenerating_subject(self):
        conversation = SavedConversation.objects.create(user=self.user, subject="Existing trip")
        conversation.messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        conversation.save()
        provider = StubAIProvider()

        result = record_turn(
            user=self.user,
            conversation=conversation,
            save_requested=True,
            user_message="more please",
            assistant_reply="sure thing",
            ai_provider=provider,
        )

        self.assertTrue(result.saved)
        self.assertIsNone(result.subject)
        conversation.refresh_from_db()
        self.assertEqual(conversation.subject, "Existing trip")
        self.assertEqual(len(conversation.messages), 4)
        # A continuing conversation already has a subject - regenerating it
        # every message would be a needless extra AI call per turn.
        self.assertEqual(provider.generate_reply_calls, [])

    def test_falls_back_to_first_message_when_subject_generation_fails(self):
        provider = StubAIProvider(fail=True)

        result = record_turn(
            user=self.user,
            conversation=None,
            save_requested=True,
            user_message="a somewhat short message",
            assistant_reply="reply",
            ai_provider=provider,
        )

        self.assertTrue(result.saved)
        self.assertEqual(result.subject, "a somewhat short message")

    def test_conversation_limit_reached_blocks_a_new_conversation(self):
        for _ in range(SavedConversation.MAX_CONVERSATIONS_PER_USER):
            SavedConversation.objects.create(user=self.user)

        result = record_turn(
            user=self.user,
            conversation=None,
            save_requested=True,
            user_message="new one",
            assistant_reply="reply",
            ai_provider=StubAIProvider(),
        )

        self.assertFalse(result.saved)
        self.assertEqual(result.reason, REASON_CONVERSATION_LIMIT_REACHED)
        self.assertEqual(
            SavedConversation.objects.count(), SavedConversation.MAX_CONVERSATIONS_PER_USER
        )

    def test_size_limit_exceeded_marks_conversation_full_but_still_saves_that_turn(self):
        conversation = SavedConversation.objects.create(user=self.user, subject="Big trip")
        conversation.messages = [
            {"role": "user", "content": "x" * (SavedConversation.MAX_CHARS - 10)},
        ]
        conversation.save()
        provider = StubAIProvider()

        result = record_turn(
            user=self.user,
            conversation=conversation,
            save_requested=True,
            user_message="y" * 20,
            assistant_reply="z" * 20,
            ai_provider=provider,
        )

        self.assertTrue(result.saved)
        self.assertEqual(result.reason, REASON_SIZE_LIMIT_EXCEEDED)
        conversation.refresh_from_db()
        self.assertTrue(conversation.is_full)
        self.assertEqual(len(conversation.messages), 3)

    def test_already_full_conversation_stops_saving_silently(self):
        conversation = SavedConversation.objects.create(user=self.user, is_full=True)
        original_messages = list(conversation.messages)

        result = record_turn(
            user=self.user,
            conversation=conversation,
            save_requested=True,
            user_message="another message",
            assistant_reply="another reply",
            ai_provider=StubAIProvider(),
        )

        self.assertFalse(result.saved)
        self.assertIsNone(result.reason)
        conversation.refresh_from_db()
        self.assertEqual(conversation.messages, original_messages)
