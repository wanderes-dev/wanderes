from django.core.cache import cache
from django.test import TestCase

from ai import memory
from ai.tests.helpers import remaining_ttl_seconds
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

    def test_append_turn_stores_the_raw_unsanitized_assistant_reply(self):
        # These exact figures, stated only by the AI (never the
        # traveler), were getting read back by a later turn's intent
        # extraction and misattributed as the traveler's own stated
        # climate/budget preference - that used to get fixed by stripping
        # them here, at storage time, which broke genuine recall ("what did
        # you suggest?") since the real figures were gone before they were
        # ever saved. The fix now lives only in ai.orchestration.
        # _sanitized_history_messages; storage always keeps the raw reply.
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
        self.assertIn("18-20°C", stored_reply)
        self.assertIn("31°C", stored_reply)
        self.assertIn("4/5", stored_reply)

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


_NO_STATE = {
    "min_temp_c": None,
    "max_temp_c": None,
    "max_cost_of_living": None,
    "trip_type": None,
    "continent": None,
    "country": None,
    "excluded_place_names": [],
}


class ClimateBudgetTests(TestCase):
    """An explicit accumulator replaces letting ai.orchestration's intent
    extraction re-derive these fields from full conversation history every
    turn (see ai.orchestration._extract_climate_budget_signal). Started out
    covering just min_temp_c/max_temp_c/max_cost_of_living (hence the
    class name); trip_type/continent/country/excluded_place_names joined
    once LOST_CONTEXT turned out to be the same "not mentioned vs.
    explicitly dropped" problem for those fields too."""

    def test_get_climate_budget_defaults_to_all_null(self):
        result = memory.get_climate_budget("chat-history:session:nonexistent")

        self.assertEqual(result, _NO_STATE)

    def test_update_climate_budget_stores_new_values(self):
        key = "chat-history:session:cb1"

        result = memory.update_climate_budget(key, min_temp_c=22, max_cost_of_living=3)

        self.assertEqual(
            result, {**_NO_STATE, "min_temp_c": 22, "max_cost_of_living": 3}
        )
        self.assertEqual(memory.get_climate_budget(key), result)

    def test_update_climate_budget_carries_forward_fields_left_null(self):
        key = "chat-history:session:cb2"
        memory.update_climate_budget(key, min_temp_c=22)

        # A later turn that says nothing new about budget shouldn't erase
        # the earlier turn's real min_temp_c signal.
        result = memory.update_climate_budget(key, max_cost_of_living=3)

        self.assertEqual(
            result, {**_NO_STATE, "min_temp_c": 22, "max_cost_of_living": 3}
        )

    def test_update_climate_budget_overwrites_when_a_new_value_is_given(self):
        key = "chat-history:session:cb3"
        memory.update_climate_budget(key, min_temp_c=18)

        result = memory.update_climate_budget(key, min_temp_c=28)

        self.assertEqual(result["min_temp_c"], 28)

    def test_different_key_does_not_inherit_accumulated_state(self):
        memory.update_climate_budget("chat-history:session:cb4a", min_temp_c=28)

        result = memory.get_climate_budget("chat-history:session:cb4b")

        self.assertIsNone(result["min_temp_c"])

    def test_clear_history_also_resets_accumulated_climate_budget(self):
        key = "chat-history:session:cb5"
        memory.update_climate_budget(key, min_temp_c=28)

        memory.clear_history(key)

        result = memory.get_climate_budget(key)
        self.assertIsNone(result["min_temp_c"])

    def test_min_temp_c_explicit_clear_overrides_the_accumulated_value(self):
        # Before this cycle, a null from the isolated call could only ever
        # mean "carry the old value forward" - there was no way to tell
        # the accumulator the traveler had actually taken a preference
        # back. min_temp_c_cleared is the fix, mirrored across all three
        # original fields.
        key = "chat-history:session:cb-clear-temp"
        memory.update_climate_budget(key, min_temp_c=28)

        result = memory.update_climate_budget(key, min_temp_c_cleared=True)

        self.assertIsNone(result["min_temp_c"])

    def test_max_cost_of_living_explicit_clear_overrides_the_accumulated_value(self):
        # This is the CONTRA-002/004/006 finding from the Cycle 2 baseline
        # ("comfort matters more than price now" couldn't clear an earlier
        # "very cheap") - now the extraction prompt can say so explicitly.
        key = "chat-history:session:cb-clear-budget"
        memory.update_climate_budget(key, max_cost_of_living=2)

        result = memory.update_climate_budget(key, max_cost_of_living_cleared=True)

        self.assertIsNone(result["max_cost_of_living"])

    def test_a_new_value_wins_over_its_own_clear_flag_in_the_same_turn(self):
        key = "chat-history:session:cb-value-beats-clear"
        memory.update_climate_budget(key, max_temp_c=30)

        result = memory.update_climate_budget(key, max_temp_c=22, max_temp_c_cleared=True)

        self.assertEqual(result["max_temp_c"], 22)

    def test_trip_type_persists_across_a_turn_that_does_not_mention_it(self):
        key = "chat-history:session:cb-trip-type-persist"
        memory.update_climate_budget(key, trip_type="beach")

        result = memory.update_climate_budget(key, max_cost_of_living=3)

        self.assertEqual(result["trip_type"], "beach")

    def test_trip_type_explicit_clear(self):
        key = "chat-history:session:cb-trip-type-clear"
        memory.update_climate_budget(key, trip_type="beach")

        result = memory.update_climate_budget(key, trip_type_cleared=True)

        self.assertIsNone(result["trip_type"])

    def test_country_clears_independently_of_continent(self):
        # The Europe-but-not-Portugal-anymore case: "actually anywhere in
        # Europe" should drop the specific country while the broader
        # continent constraint the traveler already gave stays in force.
        key = "chat-history:session:cb-country-clear"
        memory.update_climate_budget(key, continent="europe", country="Portugal")

        result = memory.update_climate_budget(key, country_cleared=True)

        self.assertEqual(result["continent"], "europe")
        self.assertIsNone(result["country"])

    def test_country_correction_replaces_the_old_value(self):
        key = "chat-history:session:cb-country-correction"
        memory.update_climate_budget(key, continent="europe", country="Portugal")

        result = memory.update_climate_budget(key, continent="europe", country="Spain")

        self.assertEqual(result["country"], "Spain")

    def test_excluded_place_names_accumulates_additions_across_turns(self):
        key = "chat-history:session:cb-exclusions-add"
        memory.update_climate_budget(key, excluded_place_names_add=["Rome"])

        result = memory.update_climate_budget(key, excluded_place_names_add=["Prague"])

        self.assertCountEqual(result["excluded_place_names"], ["Rome", "Prague"])

    def test_excluded_place_names_add_is_case_insensitively_deduplicated(self):
        key = "chat-history:session:cb-exclusions-dedupe"
        memory.update_climate_budget(key, excluded_place_names_add=["Rome"])

        result = memory.update_climate_budget(key, excluded_place_names_add=["rome"])

        self.assertEqual(result["excluded_place_names"], ["Rome"])

    def test_excluded_place_names_remove_takes_a_place_back_off_the_list(self):
        # "Actually Rome would be nice after all" - a place coming off the
        # exclusion list, not the list being wiped entirely.
        key = "chat-history:session:cb-exclusions-remove"
        memory.update_climate_budget(key, excluded_place_names_add=["Rome", "Prague"])

        result = memory.update_climate_budget(key, excluded_place_names_remove=["Rome"])

        self.assertEqual(result["excluded_place_names"], ["Prague"])

    def test_excluded_place_names_cleared_drops_the_whole_list(self):
        key = "chat-history:session:cb-exclusions-clear"
        memory.update_climate_budget(key, excluded_place_names_add=["Rome", "Prague"])

        result = memory.update_climate_budget(key, excluded_place_names_cleared=True)

        self.assertEqual(result["excluded_place_names"], [])

    def test_excluded_place_names_cleared_and_add_in_the_same_turn_starts_fresh(self):
        # "Forget my exclusions, but I don't want Rome" - a full reset
        # followed by this turn's own new exclusion, not a no-op.
        key = "chat-history:session:cb-exclusions-clear-and-add"
        memory.update_climate_budget(key, excluded_place_names_add=["Prague"])

        result = memory.update_climate_budget(
            key, excluded_place_names_cleared=True, excluded_place_names_add=["Rome"]
        )

        self.assertEqual(result["excluded_place_names"], ["Rome"])


class ResolveStateDeltaTests(TestCase):
    """resolve_state_delta() is update_climate_budget()'s merge logic
    without persistence - used by ai.orchestration for a caller with no
    conv_key to accumulate into (a saved-conversation resume)."""

    def test_defaults_to_merging_against_blank_state(self):
        result = memory.resolve_state_delta(trip_type="beach")

        self.assertEqual(result["trip_type"], "beach")
        self.assertIsNone(result["country"])

    def test_merges_against_an_explicitly_given_current_state(self):
        current = {**_NO_STATE, "trip_type": "beach", "country": "Portugal"}

        result = memory.resolve_state_delta(current, country_cleared=True)

        self.assertEqual(result["trip_type"], "beach")
        self.assertIsNone(result["country"])

    def test_does_not_write_to_the_cache(self):
        memory.resolve_state_delta(trip_type="beach")

        self.assertEqual(
            memory.get_climate_budget("chat-history:session:resolve-does-not-persist"), _NO_STATE
        )


class StateLifetimeTests(TestCase):
    """The accumulated traveler state and the turn history are one
    conversation, so they age out together - however the turns in between
    were handled."""

    def _age_state(self, key, seconds=5):
        cache.touch(memory._climate_budget_key(key), seconds)
        self.assertLessEqual(remaining_ttl_seconds(memory._climate_budget_key(key)), seconds)

    def test_append_turn_refreshes_the_states_lifetime(self):
        key = "chat-history:session:ttl-refresh"
        memory.update_climate_budget(key, trip_type="beach")
        self._age_state(key)

        memory.append_turn(key, user_message="hi", assistant_reply="hello")

        self.assertGreater(
            remaining_ttl_seconds(memory._climate_budget_key(key)),
            memory.CONVERSATION_TTL_SECONDS - 60,
        )

    def test_state_and_history_lifetimes_stay_in_step_over_many_turns(self):
        key = "chat-history:session:ttl-in-step"
        memory.update_climate_budget(key, country="Italy")
        self._age_state(key)

        # Turns that never touch the state itself (nothing to merge).
        for i in range(4):
            memory.append_turn(key, user_message=f"aside {i}", assistant_reply="ok")

        state_ttl = remaining_ttl_seconds(memory._climate_budget_key(key))
        history_ttl = remaining_ttl_seconds(key)
        self.assertAlmostEqual(state_ttl, history_ttl, delta=5)

    def test_append_turn_does_not_invent_state_for_a_conversation_without_any(self):
        key = "chat-history:session:ttl-no-state"

        memory.append_turn(key, user_message="hi", assistant_reply="hello")

        self.assertIsNone(remaining_ttl_seconds(memory._climate_budget_key(key)))
        self.assertEqual(memory.get_climate_budget(key), _NO_STATE)

    def test_clear_history_still_removes_both_keys(self):
        key = "chat-history:session:ttl-clear"
        memory.update_climate_budget(key, trip_type="beach")
        memory.append_turn(key, user_message="hi", assistant_reply="hello")

        memory.clear_history(key)

        self.assertIsNone(remaining_ttl_seconds(key))
        self.assertIsNone(remaining_ttl_seconds(memory._climate_budget_key(key)))

    def test_refreshing_the_lifetime_leaves_set_unchanged_and_clear_semantics_alone(self):
        key = "chat-history:session:ttl-semantics"
        memory.update_climate_budget(key, country="Italy", trip_type="culture")

        # UNCHANGED: a turn with nothing to say about the state.
        memory.append_turn(key, user_message="aside", assistant_reply="ok")
        state = memory.get_climate_budget(key)
        self.assertEqual((state["country"], state["trip_type"]), ("Italy", "culture"))

        # SET replaces one field and leaves the rest.
        memory.update_climate_budget(key, country="Spain")
        memory.append_turn(key, user_message="aside", assistant_reply="ok")
        state = memory.get_climate_budget(key)
        self.assertEqual((state["country"], state["trip_type"]), ("Spain", "culture"))

        # CLEAR drops exactly the cleared field.
        memory.update_climate_budget(key, country_cleared=True)
        memory.append_turn(key, user_message="aside", assistant_reply="ok")
        state = memory.get_climate_budget(key)
        self.assertEqual((state["country"], state["trip_type"]), (None, "culture"))
