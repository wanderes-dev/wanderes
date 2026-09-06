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

    def test_append_turn_strips_temperature_and_cost_tier_from_assistant_reply(self):
        # 2026-09-06 bug: these exact figures, stated only by the AI itself
        # (never the traveler), were being read back by a later turn's
        # intent extraction and misattributed as the traveler's own stated
        # climate/budget preference.
        key = "chat-history:session:test4"

        memory.append_turn(
            key,
            user_message="quero uma praia mais refinada para dezembro",
            assistant_reply=(
                "Santorini (18-20°C, custo 4/5) e Phuket (31°C, custo 4/5) "
                "sao boas opcoes."
            ),
        )

        history = memory.get_history(key)
        stored_reply = history[1]["content"]
        self.assertNotIn("18-20°C", stored_reply)
        self.assertNotIn("31°C", stored_reply)
        self.assertNotIn("4/5", stored_reply)
        self.assertIn("[temp]", stored_reply)
        self.assertIn("[cost]", stored_reply)

    def test_append_turn_leaves_ordinary_replies_unchanged(self):
        key = "chat-history:session:test5"

        memory.append_turn(
            key, user_message="hi", assistant_reply="Bali is a great beach destination."
        )

        history = memory.get_history(key)
        self.assertEqual(history[1]["content"], "Bali is a great beach destination.")


class SanitizeReplyForContextTests(TestCase):
    def test_strips_temperature_figures(self):
        result = memory.sanitize_reply_for_context("Highs around 31°C, sometimes 18-20°C.")

        self.assertNotIn("31°C", result)
        self.assertNotIn("18-20°C", result)
        self.assertIn("[temp]", result)

    def test_strips_cost_tier_figures(self):
        result = memory.sanitize_reply_for_context("Cost tier 4/5, quite pricey.")

        self.assertNotIn("4/5", result)
        self.assertIn("[cost]", result)

    def test_leaves_unrelated_text_unchanged(self):
        text = "Bali has beautiful beaches and a low cost of living."

        self.assertEqual(memory.sanitize_reply_for_context(text), text)
