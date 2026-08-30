from django.test import TestCase

from ai import memory
from users.models import User


class ConversationKeyTests(TestCase):
    def test_authenticated_user_keyed_by_account(self):
        user = User.objects.create_user(email="traveler@example.com", password="testpass123")

        key = memory.conversation_key(user=user, session_key="abc123")

        self.assertEqual(key, f"chat-history:user:{user.pk}")

    def test_anonymous_user_keyed_by_session(self):
        key = memory.conversation_key(user=None, session_key="abc123")

        self.assertEqual(key, "chat-history:session:abc123")

    def test_unauthenticated_user_object_keyed_by_session(self):
        class _Anonymous:
            is_authenticated = False

        key = memory.conversation_key(user=_Anonymous(), session_key="abc123")

        self.assertEqual(key, "chat-history:session:abc123")


class HistoryStorageTests(TestCase):
    def test_get_history_defaults_to_empty_list(self):
        self.assertEqual(memory.get_history("chat-history:session:nonexistent"), [])

    def test_append_turn_stores_user_and_assistant_messages(self):
        key = "chat-history:session:test1"

        memory.append_turn(key, user_message="Hi", assistant_reply="Hello!")

        history = memory.get_history(key)
        self.assertEqual(
            history,
            [{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello!"}],
        )

    def test_append_turn_accumulates_across_calls(self):
        key = "chat-history:session:test2"

        memory.append_turn(key, user_message="Hi", assistant_reply="Hello!")
        memory.append_turn(key, user_message="How are you?", assistant_reply="Great, thanks!")

        history = memory.get_history(key)
        self.assertEqual(len(history), 4)
        self.assertEqual(history[2], {"role": "user", "content": "How are you?"})

    def test_history_trimmed_to_max_messages(self):
        key = "chat-history:session:test3"

        for i in range(10):
            memory.append_turn(key, user_message=f"message {i}", assistant_reply=f"reply {i}")

        history = memory.get_history(key)
        self.assertEqual(len(history), memory.MAX_HISTORY_MESSAGES)
        # The oldest turns should have been dropped, keeping the most recent.
        self.assertEqual(history[-1], {"role": "assistant", "content": "reply 9"})
