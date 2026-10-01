"""Saved-conversation continuity of the accumulated traveler state, through
the real /api/v1/recommendations/ view - the path a signed-in traveler with
"Save this conversation" left on takes, where every turn from the second on
arrives as a history_override.

The state is per user, so these tests play several tabs against one account.
Each thread writes a distinct min_temp_c (X=20, Y=21, U=22) so a turn that
reads another thread's state shows up as a foreign value.
"""

from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from ai import memory
from ai.models import SavedConversation
from ai.tests.helpers import (
    FixedClimateProvider,
    InterleavingCache,
    ScriptedProvider,
    intent,
    make_destination,
    remaining_ttl_seconds,
)
from evaluations.view_path import ViewSession
from users.models import User

X, Y, U = 20, 21, 22
_MERGE_PATH_CALLS = ["travel_message", "climate_budget_signal", "traveler_state_clear_signal"]


def t(min_temp=None, **intent_fields):
    return {
        "intent": intent(**intent_fields),
        "climate_budget": {} if min_temp is None else {"min_temp_c": min_temp},
        "state_clear": {},
    }


def early_return():
    return {"intent": intent(message_type="off_topic"), "climate_budget": {}, "state_clear": {}}


class _SavedConversationCase(TestCase):
    def setUp(self):
        make_destination("rome-it", name="Rome", country="Italy", trip_type="culture")
        self.climate = FixedClimateProvider()
        self.user = User.objects.create_user(email="saver@example.com", password="x")
        self.other = User.objects.create_user(email="other@example.com", password="x")
        self.key = memory.conversation_key(user=self.user, session_key=None)

    def tab(self, script, *, save=True, user=None):
        provider = ScriptedProvider(script)
        session = ViewSession(
            self.user if user is None else user,
            ai_provider=provider,
            climate_provider=self.climate,
            save=save,
        )
        return session, provider

    def state(self):
        return memory.get_climate_budget(self.key)

    def owner(self):
        return memory.get_state_owner(self.key)

    def owns(self, conversation_id):
        return memory.state_owned_by(self.key, conversation_id)

    def assert_left_alone(self, before_state, before_owner, before_history):
        self.assertEqual(self.state(), before_state)
        self.assertEqual(self.owner(), before_owner)
        self.assertEqual(memory.get_history(self.key), before_history)

    def snapshot(self):
        return self.state(), self.owner(), memory.get_history(self.key)


class SameConversationContinuityTests(_SavedConversationCase):
    def test_default_saved_conversation_retains_its_own_state_across_turns(self):
        x, _ = self.tab([t(X, trip_type="culture"), t(), t()])

        first = x.post("m1")
        self.assertTrue(first.saved)
        self.assertIsNone(first.view_kwargs["history_override"])  # turn 1 is on the Redis path
        self.assertTrue(str(first.view_kwargs["thread_id"]).startswith("pending:"))
        self.assertTrue(self.owns(x.conversation_id))  # the pending token was promoted

        for message in ("m2", "m3"):
            turn = x.post(message)
            self.assertIsNotNone(turn.view_kwargs["history_override"])
            self.assertEqual(turn.view_kwargs["thread_id"], x.conversation_id)
            self.assertEqual(turn.intent["min_temp_c"], X)  # carried over from turn 1
            self.assertEqual(turn.intent["trip_type"], "culture")
            self.assertEqual(turn.state["min_temp_c"], X)
            self.assertEqual(turn.state, self.state())  # state_sink = what's persisted
        self.assertEqual(self.owner(), x.conversation_id)

    def test_the_history_the_ai_sees_comes_from_the_saved_conversation(self):
        x, provider = self.tab([t(X), t(), t()])

        x.post("first")
        x.post("second")
        x.post("third")

        seen_at_turn_3 = [m.content for m in provider.intent_messages[2]]
        self.assertIn("second", seen_at_turn_3)
        # Redis history stops at turn 1: owned override turns don't copy text into it.
        self.assertNotIn("second", [m["content"] for m in memory.get_history(self.key)])

    def test_continuation_turns_make_no_additional_model_calls(self):
        x, provider = self.tab([t(X), t(), t()])

        for message in ("a", "b", "c"):
            x.post(message)

        # Turn 1 on the Redis path, turns 2 and 3 with a history_override and
        # state in play - the same calls on every one. (The title for the new
        # conversation comes from a separate provider.)
        self.assertEqual(provider.structured_calls, _MERGE_PATH_CALLS * 3)
        self.assertEqual((provider.reply_calls, provider.stream_calls), (0, 3))

    def test_ttl_is_refreshed_by_an_owned_turn_that_returns_early(self):
        x, _ = self.tab([t(X), t(), early_return()])
        x.post("x1")
        x.post("x2")
        cache.touch(memory._state_owner_key(self.key), 5)
        cache.touch(memory._climate_budget_key(self.key), 5)

        x.post("an aside")

        floor = memory.CONVERSATION_TTL_SECONDS - 60
        self.assertGreater(remaining_ttl_seconds(memory._state_owner_key(self.key)), floor)
        self.assertGreater(remaining_ttl_seconds(memory._climate_budget_key(self.key)), floor)


class OwnershipMismatchTests(_SavedConversationCase):
    def test_owner_mismatch_fails_closed_and_leaves_the_other_conversations_state_alone(self):
        x, _ = self.tab([t(X), t(), t()])
        y, _ = self.tab([t(Y), t(), t()])
        x.post("x1")
        y.post("y1")  # Y now owns the state
        before = self.snapshot()

        turn = x.post("x2")

        self.assertEqual(turn.state, {})  # ran stateless
        self.assertIsNone(turn.intent["min_temp_c"])
        self.assertIsNotNone(turn.view_kwargs["history_override"])  # history still from the save
        self.assert_left_alone(*before)
        self.assertEqual(self.state()["min_temp_c"], Y)

    def test_two_saved_tabs_interleaved_never_see_each_others_state(self):
        x, _ = self.tab([t(X), t(), t()])
        y, _ = self.tab([t(Y), t(), t()])
        x.post("x1")
        y.post("y1")

        outcomes = [x.post("x2"), y.post("y2"), x.post("x3"), y.post("y3")]

        x2, y2, x3, y3 = outcomes
        self.assertEqual((x2.state, x3.state), ({}, {}))  # X lost the slot to Y: stateless
        self.assertEqual(y2.intent["min_temp_c"], Y)  # Y keeps its own
        self.assertEqual(y3.intent["min_temp_c"], Y)
        self.assertEqual(self.state()["min_temp_c"], Y)
        self.assertTrue(self.owns(y.conversation_id))

    def test_an_unsaved_tab_invalidates_ownership(self):
        x, _ = self.tab([t(X), t(), t()])
        unsaved, _ = self.tab([t(U)], save=False)
        x.post("x1")
        self.assertTrue(self.owns(x.conversation_id))

        unsaved.post("u1")  # an untracked Redis-path turn writes the shared state
        self.assertIsNone(self.owner())  # ...and takes ownership away from X
        before = self.snapshot()
        turn = x.post("x2")

        self.assertEqual(turn.state, {})
        self.assertIsNone(turn.intent["min_temp_c"])
        self.assert_left_alone(*before)
        self.assertEqual(self.state()["min_temp_c"], U)

    def test_a_missing_owner_with_existing_state_fails_closed(self):
        x, _ = self.tab([t(X), t(), t()])
        x.post("x1")
        cache.delete(memory._state_owner_key(self.key))  # the owner record expired first
        before = self.snapshot()

        turn = x.post("x2")

        self.assertEqual(turn.state, {})
        self.assertIsNone(turn.intent["min_temp_c"])
        self.assert_left_alone(*before)

    def test_identical_last_message_pairs_do_not_establish_identity(self):
        x, _ = self.tab([t(X), t(), t()])
        y, _ = self.tab([t(Y), t(), t()])
        x.post("hello")
        y.post("hello")  # the scripted reply is identical too
        saved_x = SavedConversation.objects.get(pk=x.conversation_id)
        saved_y = SavedConversation.objects.get(pk=y.conversation_id)
        self.assertEqual(saved_x.messages[-2:], saved_y.messages[-2:])
        before = self.snapshot()

        turn = x.post("hello")

        self.assertEqual(turn.state, {})
        self.assertIsNone(turn.intent["min_temp_c"])
        self.assert_left_alone(*before)
        self.assertEqual(self.state()["min_temp_c"], Y)


class EmptySlotAndResumeTests(_SavedConversationCase):
    def test_redis_expiry_then_a_valid_continuation_adopts_the_empty_slot(self):
        x, _ = self.tab([t(X), t(23), t()])
        x.post("x1")
        for k in (
            self.key,
            memory._climate_budget_key(self.key),
            memory._state_owner_key(self.key),
        ):
            cache.delete(k)  # what the TTL (or a Redis restart) does

        adopted = x.post("x2")
        after = x.post("x3")

        self.assertEqual(adopted.intent["min_temp_c"], 23)  # started blank: turn 1's 20 is gone
        self.assertEqual(self.owner(), x.conversation_id)
        self.assertEqual(after.intent["min_temp_c"], 23)  # and accumulates from there

    def test_new_conversation_clears_ownership_and_state(self):
        x, _ = self.tab([t(X), t(), t(24), t()])
        x.post("x1")
        x.post("x2")
        old_id = x.conversation_id

        x.new_conversation()

        self.assertIsNone(self.owner())
        self.assertEqual(self.state(), memory._NO_CLIMATE_BUDGET)
        fresh = x.post("z1")  # a new thread, Redis path
        again = x.post("z2")
        self.assertNotEqual(x.conversation_id, old_id)
        self.assertEqual(fresh.intent["min_temp_c"], 24)  # the old thread's 20 didn't survive
        self.assertEqual(again.intent["min_temp_c"], 24)

    def test_resuming_an_older_conversation_after_a_reset_claims_the_empty_slot(self):
        x, _ = self.tab([t(X), t()])
        x.post("x1")
        x.post("x2")
        old_id = x.conversation_id
        x.new_conversation()
        resumed, _ = self.tab([t(23), t()])
        resumed.conversation_id = old_id  # picked from the sidebar

        first = resumed.post("back again")
        second = resumed.post("and again")

        self.assertIsNone(first.state.get("trip_type"))  # nothing inherited or reconstructed
        self.assertEqual(first.intent["min_temp_c"], 23)
        self.assertEqual(second.intent["min_temp_c"], 23)
        self.assertEqual(self.owner(), old_id)

    def test_resuming_an_older_conversation_while_another_owns_the_slot_fails_closed(self):
        x, _ = self.tab([t(X), t()])
        x.post("x1")
        x.post("x2")
        old_id = x.conversation_id
        y, _ = self.tab([t(Y), t()])
        y.post("y1")  # a newer saved conversation owns the state now
        resumed, _ = self.tab([t(23), t()])
        resumed.conversation_id = old_id
        before = self.snapshot()

        turn = resumed.post("back to the old one")

        self.assertEqual(turn.state, {})
        self.assertEqual(turn.intent["min_temp_c"], 23)  # only its own message
        self.assert_left_alone(*before)


class SavingEdgeCaseTests(_SavedConversationCase):
    def test_a_failed_first_save_leaves_the_thread_working_on_the_redis_path(self):
        x, _ = self.tab([t(X), t(), t()])
        with mock.patch("ai.conversations._record_turn", side_effect=RuntimeError("boom")):
            first = x.post("x1")
        self.assertFalse(first.saved)
        self.assertIsNone(x.conversation_id)

        second = x.post("x2")  # no id yet, so still the Redis path - and it saves this time
        third = x.post("x3")

        self.assertEqual(second.intent["min_temp_c"], X)
        self.assertTrue(second.saved)
        self.assertIsNotNone(third.view_kwargs["history_override"])
        self.assertEqual(third.intent["min_temp_c"], X)
        self.assertTrue(self.owns(x.conversation_id))

    def test_a_failed_later_save_does_not_break_continuity(self):
        x, _ = self.tab([t(X), t(), t(), t()])
        x.post("x1")
        x.post("x2")
        with mock.patch("ai.conversations._record_turn", side_effect=RuntimeError("boom")):
            failed = x.post("x3")
        self.assertFalse(failed.saved)

        after = x.post("x4")  # the saved copy is behind, but ownership is by id

        self.assertEqual(after.intent["min_temp_c"], X)
        self.assertEqual(self.owner(), x.conversation_id)

    def test_the_size_cap_does_not_break_continuity(self):
        x, _ = self.tab([t(X), t(), t()])
        x.post("x1")
        SavedConversation.objects.filter(pk=x.conversation_id).update(is_full=True)

        second = x.post("x2")  # no longer persisted...
        third = x.post("x3")

        self.assertFalse(second.saved)
        self.assertEqual(second.intent["min_temp_c"], X)  # ...but the state still carries
        self.assertEqual(third.intent["min_temp_c"], X)

    def test_ticking_the_box_mid_thread_keeps_the_threads_state(self):
        x, _ = self.tab([t(X), t(), t()], save=False)
        x.post("x1")  # unsaved
        x.save = True

        second = x.post("x2")  # the conversation is created here (only this turn is saved)
        third = x.post("x3")

        self.assertTrue(second.saved)
        self.assertEqual(second.intent["min_temp_c"], X)
        self.assertIsNotNone(third.view_kwargs["history_override"])
        self.assertEqual(third.intent["min_temp_c"], X)  # the pending owner was promoted
        self.assertTrue(self.owns(x.conversation_id))

    def test_a_lost_promotion_race_fails_closed(self):
        x, _ = self.tab([t(X), t()])
        real_promote = memory.promote_state_owner

        def another_tab_writes_first(key, pending, conversation_id):
            memory.update_climate_budget(key, min_temp_c=99)  # an untracked write lands first
            return real_promote(key, pending, conversation_id)

        with mock.patch("ai.memory.promote_state_owner", side_effect=another_tab_writes_first):
            x.post("x1")
        self.assertFalse(self.owns(x.conversation_id))
        before = self.snapshot()

        turn = x.post("x2")

        self.assertEqual(turn.state, {})
        self.assertIsNone(turn.intent["min_temp_c"])
        self.assert_left_alone(*before)
        self.assertEqual(self.state()["min_temp_c"], 99)


class ConversationIdValidationTests(_SavedConversationCase):
    def test_a_stale_id_is_dropped_and_the_turn_is_a_new_thread(self):
        x, _ = self.tab([t(X)])

        turn = x.post("hello", conversation_id=999999)

        self.assertIsNone(turn.view_kwargs["history_override"])
        self.assertTrue(str(turn.view_kwargs["thread_id"]).startswith("pending:"))
        self.assertTrue(turn.saved)  # saved as a brand-new conversation

    def test_another_users_conversation_id_is_dropped_and_their_data_untouched(self):
        theirs = SavedConversation.objects.create(
            user=self.other,
            subject="theirs",
            messages=[{"role": "user", "content": "private"}],
        )
        their_key = memory.conversation_key(user=self.other, session_key=None)
        x, _ = self.tab([t(X)])

        turn = x.post("hello", conversation_id=theirs.pk)

        self.assertIsNone(turn.view_kwargs["history_override"])
        self.assertNotEqual(turn.conversation_id, theirs.pk)
        theirs.refresh_from_db()
        self.assertEqual(theirs.messages, [{"role": "user", "content": "private"}])
        self.assertIsNone(memory.get_state_owner(their_key))

    def test_an_anonymous_visitor_is_unchanged(self):
        provider = ScriptedProvider([t(X), t(), t()])
        anonymous = ViewSession(None, ai_provider=provider, climate_provider=self.climate)

        first = anonymous.post("a1")
        second = anonymous.post("a2", conversation_id=1)  # an id from a client is ignored
        third = anonymous.post("a3")

        for turn in (first, second, third):
            self.assertIsNone(turn.view_kwargs["thread_id"])
            self.assertIsNone(turn.view_kwargs["history_override"])
            self.assertFalse(turn.saved)
        self.assertEqual(third.intent["min_temp_c"], X)  # the ordinary session-keyed Redis path
        self.assertEqual(SavedConversation.objects.count(), 0)


class ConversationDeletionTests(_SavedConversationCase):
    def _delete(self, session, conversation_id):
        session.client.post(reverse("ai:conversation-delete", args=[conversation_id]))

    def test_deleting_the_owning_conversation_leaves_its_ownership_inert(self):
        y, _ = self.tab([t(Y), t(), t()])
        x, _ = self.tab([t(X), t()])
        y.post("y1")
        x.post("x1")
        x.post("x2")
        deleted_id = x.conversation_id
        self.assertEqual(self.owner(), deleted_id)
        state_before = self.state()

        self._delete(x, deleted_id)

        self.assertFalse(SavedConversation.objects.filter(pk=deleted_id).exists())
        self.assertEqual(self.owner(), deleted_id)  # nothing was released
        self.assertEqual(self.state(), state_before)
        # A deleted id is never handed out again, so the record can't vouch for
        # anyone else: another saved conversation gets nothing out of it...
        turn = y.post("y2")
        self.assertEqual(turn.state, {})
        self.assertIsNone(turn.intent["min_temp_c"])
        self.assertEqual(self.owner(), deleted_id)
        self.assertEqual(self.state(), state_before)
        # ...until a reset (or the expiry) frees the slot.
        memory.clear_history(self.key)
        y.post("y3")
        self.assertTrue(self.owns(y.conversation_id))

    def test_deleting_a_conversation_performs_no_ownership_operation_at_all(self):
        x, _ = self.tab([t(X)])
        x.post("x1")
        recorder = InterleavingCache(cache)

        with mock.patch("ai.memory.cache", recorder):
            self._delete(x, x.conversation_id)

        self.assertEqual(
            [op for op, _ in recorder.ops if op in ("set", "add", "delete", "touch")], []
        )
        self.assertTrue(self.owns(x.conversation_id))

    def test_deleting_a_conversation_that_does_not_own_the_state_leaves_ownership_alone(self):
        x, _ = self.tab([t(X), t()])
        y, _ = self.tab([t(Y), t()])
        x.post("x1")
        y.post("y1")

        self._delete(x, x.conversation_id)  # X isn't the owner

        self.assertFalse(SavedConversation.objects.filter(pk=x.conversation_id).exists())
        self.assertTrue(self.owns(y.conversation_id))
        self.assertEqual(self.state()["min_temp_c"], Y)
