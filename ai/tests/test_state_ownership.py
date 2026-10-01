"""Who owns the accumulated traveler state.

The state lives under a per-user key, but a signed-in user can have several
saved conversations (and tabs). A saved conversation continued with a
history_override may only read or write that state once it provably owns it;
otherwise it runs stateless, exactly as it always did.
"""

import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import mock

from django.core.cache import cache
from django.test import TestCase

from ai import memory
from ai.orchestration import stream_travel_recommendation
from ai.tests.helpers import (
    FixedClimateProvider,
    InterleavingCache,
    ScriptedProvider,
    StateWriteSpy,
    intent,
    make_destination,
    remaining_ttl_seconds,
)
from users.models import User

_MERGE_PATH_CALLS = ["travel_message", "climate_budget_signal", "traveler_state_clear_signal"]


def _t(intent_fields=None, climate=None):
    return {
        "intent": intent(**(intent_fields or {})),
        "climate_budget": climate or {},
        "state_clear": {},
    }


class StateOwnerMemoryTests(TestCase):
    def setUp(self):
        self.key = "chat-history:user:ownership"

    def _owner_key(self):
        return memory._state_owner_key(self.key)

    def test_an_owned_write_stamps_the_owner_and_an_unowned_write_clears_it(self):
        memory.update_climate_budget(self.key, trip_type="beach", owner=7)
        self.assertEqual(memory.get_state_owner(self.key), 7)

        # Forgetting to say who's writing must fail closed, not keep the old owner.
        memory.update_climate_budget(self.key, country="Italy")

        self.assertIsNone(memory.get_state_owner(self.key))

    def _mutations_of(self, action):
        """The cache mutations `action` performs, in order, as (op, what)."""
        recorder = InterleavingCache(cache)
        with mock.patch("ai.memory.cache", recorder):
            action()
        return [(op, what) for op, what in recorder.ops if op in ("set", "delete", "add")]

    def test_every_write_invalidates_the_owner_before_it_touches_the_state(self):
        memory.update_climate_budget(self.key, trip_type="beach", owner=3)

        unowned = self._mutations_of(
            lambda: memory.update_climate_budget(self.key, trip_type="city")
        )
        owned = self._mutations_of(
            lambda: memory.update_climate_budget(self.key, trip_type="city", owner=4)
        )

        # Invalidate -> write the state -> stamp. An unowned write has no stamp
        # to make, so it drops the owner again instead (a claim landing in the
        # gap must not be left vouching for state it never saw).
        self.assertEqual(
            unowned,
            [("delete", "state-owner"), ("set", "climate-budget"), ("delete", "state-owner")],
        )
        self.assertEqual(
            owned,
            [("delete", "state-owner"), ("set", "climate-budget"), ("set", "state-owner")],
        )

    def test_the_old_owner_cannot_observe_a_foreign_writers_state_while_still_the_owner(self):
        # Whatever the foreign writer is (unsaved, a pending first turn or
        # another saved conversation), the old owner must already be invalid by
        # the time the new state is visible, and stays invalid afterwards.
        cases = {
            "unowned": None,
            "pending": memory.new_pending_owner(),
            "another conversation": 9,
        }
        for label, writer_owner in cases.items():
            with self.subTest(writer=label):
                memory.clear_history(self.key)
                memory.update_climate_budget(self.key, trip_type="beach", owner=5)
                seen = []

                def the_old_owner_looks(seen=seen):
                    state = memory.get_climate_budget(self.key)
                    seen.append((state["trip_type"], memory.state_owned_by(self.key, 5)))

                hooked = InterleavingCache(cache)
                hooked.after("set", ":climate-budget", the_old_owner_looks)
                with mock.patch("ai.memory.cache", hooked):
                    memory.update_climate_budget(self.key, trip_type="city", owner=writer_owner)

                # Right after the foreign state landed the old owner was already out.
                self.assertEqual(seen, [("city", False)])
                self.assertFalse(memory.state_owned_by(self.key, 5))

    def test_an_unowned_write_ends_with_no_owner_even_if_a_claim_landed_in_its_gap(self):
        hooked = InterleavingCache(cache)

        def a_claim_lands_between_the_delete_and_the_state_write():
            self.assertTrue(memory.claim_empty_state_slot(self.key, 5))

        hooked.after("delete", ":state-owner", a_claim_lands_between_the_delete_and_the_state_write)
        with mock.patch("ai.memory.cache", hooked):
            memory.update_climate_budget(self.key, trip_type="beach")  # unowned

        self.assertIsNone(memory.get_state_owner(self.key))
        self.assertFalse(memory.state_owned_by(self.key, 5))
        self.assertEqual(memory.get_climate_budget(self.key)["trip_type"], "beach")

    def test_a_stamping_write_replaces_whatever_landed_in_its_gap(self):
        hooked = InterleavingCache(cache)

        def a_claim_lands_between_the_delete_and_the_state_write():
            self.assertTrue(memory.claim_empty_state_slot(self.key, 5))

        hooked.after("delete", ":state-owner", a_claim_lands_between_the_delete_and_the_state_write)
        with mock.patch("ai.memory.cache", hooked):
            memory.update_climate_budget(self.key, trip_type="beach", owner=8)

        self.assertEqual(memory.get_state_owner(self.key), 8)
        self.assertTrue(memory.state_owned_by(self.key, 8))
        self.assertFalse(memory.state_owned_by(self.key, 5))

    def test_a_pending_owner_promoted_to_an_id_is_owned_by_that_conversation(self):
        pending = memory.new_pending_owner()
        self.assertTrue(pending.startswith("pending:"))
        memory.update_climate_budget(self.key, trip_type="beach", owner=pending)
        self.assertFalse(memory.state_owned_by(self.key, 5))  # not promoted yet

        self.assertTrue(memory.promote_state_owner(self.key, pending, 5))

        self.assertTrue(memory.state_owned_by(self.key, 5))
        self.assertFalse(memory.state_owned_by(self.key, 6))
        # Promotion is not a write to the owner record: there's no compare-and-set
        # in Django's cache, so it never replaces anything.
        self.assertEqual(memory.get_state_owner(self.key), pending)

    def test_promotion_is_single_shot_and_cannot_be_retargeted(self):
        pending = memory.new_pending_owner()
        memory.update_climate_budget(self.key, trip_type="beach", owner=pending)
        self.assertTrue(memory.promote_state_owner(self.key, pending, 5))

        self.assertFalse(memory.promote_state_owner(self.key, pending, 6))

        self.assertTrue(memory.state_owned_by(self.key, 5))
        self.assertFalse(memory.state_owned_by(self.key, 6))

    def test_a_promotion_is_not_honoured_once_anyone_else_has_written_the_state(self):
        # The lost race: the conversation is saved (promotion recorded) but
        # another thread took the state in between.
        pending = memory.new_pending_owner()
        memory.update_climate_budget(self.key, trip_type="beach", owner=pending)
        memory.update_climate_budget(self.key, country="Italy")  # an unowned write lands first

        self.assertTrue(memory.promote_state_owner(self.key, pending, 5))  # recorded...

        self.assertFalse(memory.state_owned_by(self.key, 5))  # ...but never consulted

    def test_a_promotion_is_not_honoured_once_another_pending_owner_took_over(self):
        first = memory.new_pending_owner()
        second = memory.new_pending_owner()
        memory.update_climate_budget(self.key, trip_type="beach", owner=first)
        memory.update_climate_budget(self.key, trip_type="city", owner=second)

        memory.promote_state_owner(self.key, first, 5)
        memory.promote_state_owner(self.key, second, 6)

        self.assertFalse(memory.state_owned_by(self.key, 5))
        self.assertTrue(memory.state_owned_by(self.key, 6))

    def test_only_pending_tokens_can_be_promoted(self):
        self.assertFalse(memory.promote_state_owner(self.key, "not-a-pending-token", 5))

    def test_unrecognised_owner_values_are_never_owned(self):
        for value in ("a-random-string", True, 3.5, ["x"]):
            with self.subTest(owner=value):
                cache.set(self._owner_key(), value, memory.CONVERSATION_TTL_SECONDS)
                self.assertFalse(memory.state_owned_by(self.key, 1))

    def test_an_empty_slot_can_be_claimed_and_starts_blank(self):
        self.assertTrue(memory.claim_empty_state_slot(self.key, 5))

        self.assertTrue(memory.state_owned_by(self.key, 5))
        self.assertFalse(memory.state_owned_by(self.key, 6))
        self.assertEqual(memory.get_climate_budget(self.key), memory._NO_CLIMATE_BUDGET)
        claim = memory.get_state_owner(self.key)
        self.assertFalse(memory.claim_empty_state_slot(self.key, 6))  # already taken
        self.assertEqual(memory.get_state_owner(self.key), claim)  # and left alone
        self.assertTrue(memory.state_owned_by(self.key, 5))

    def test_the_claim_is_a_unique_token_that_only_the_claimant_can_turn_into_ownership(self):
        memory.claim_empty_state_slot(self.key, 5)
        token = memory.get_state_owner(self.key)

        self.assertTrue(token.startswith("pending:"))
        # Nobody else can ride on the token: promotion is single-shot.
        self.assertFalse(memory.promote_state_owner(self.key, token, 6))
        self.assertFalse(memory.state_owned_by(self.key, 6))
        self.assertTrue(memory.state_owned_by(self.key, 5))

    def test_a_slot_with_state_but_no_owner_is_not_empty(self):
        # Missing/expired owner with existing state: nobody can vouch for it.
        memory.update_climate_budget(self.key, trip_type="beach")

        self.assertFalse(memory.claim_empty_state_slot(self.key, 5))

        self.assertIsNone(memory.get_state_owner(self.key))
        self.assertEqual(memory.get_climate_budget(self.key)["trip_type"], "beach")

    def test_a_slot_with_an_owner_is_not_empty_even_without_state(self):
        cache.set(self._owner_key(), 9, memory.CONVERSATION_TTL_SECONDS)

        self.assertFalse(memory.claim_empty_state_slot(self.key, 5))

        self.assertEqual(memory.get_state_owner(self.key), 9)

    def test_racing_claims_on_an_empty_slot_have_exactly_one_winner(self):
        contenders = 12
        barrier = Barrier(contenders)

        def contend(conversation_id):
            barrier.wait()
            return conversation_id, memory.claim_empty_state_slot(self.key, conversation_id)

        with ThreadPoolExecutor(max_workers=contenders) as pool:
            outcomes = list(pool.map(contend, range(1, contenders + 1)))

        winners = [cid for cid, won in outcomes if won]
        self.assertEqual(len(winners), 1)
        for conversation_id in range(1, contenders + 1):
            self.assertEqual(
                memory.state_owned_by(self.key, conversation_id), conversation_id == winners[0]
            )

    def test_claim_state_for_conversation_uses_ownership_or_an_empty_slot_only(self):
        # Already the owner: yes, and nothing changes.
        memory.update_climate_budget(self.key, trip_type="beach", owner=5)
        self.assertTrue(memory.claim_state_for_conversation(self.key, 5))
        # Someone else's: no, and it's left alone.
        self.assertFalse(memory.claim_state_for_conversation(self.key, 6))
        self.assertEqual(memory.get_state_owner(self.key), 5)
        self.assertEqual(memory.get_climate_budget(self.key)["trip_type"], "beach")
        # An empty slot: yes.
        memory.clear_history(self.key)
        self.assertTrue(memory.claim_state_for_conversation(self.key, 6))

    def test_refreshing_the_lifetime_restarts_the_owners_clock_with_the_states(self):
        memory.update_climate_budget(self.key, trip_type="beach", owner=5)
        cache.touch(self._owner_key(), 5)
        cache.touch(memory._climate_budget_key(self.key), 5)

        memory.append_turn(self.key, user_message="hi", assistant_reply="hello")

        floor = memory.CONVERSATION_TTL_SECONDS - 60
        self.assertGreater(remaining_ttl_seconds(self._owner_key()), floor)
        self.assertGreater(remaining_ttl_seconds(memory._climate_budget_key(self.key)), floor)

    def test_refreshing_the_lifetime_never_invents_an_owner(self):
        memory.refresh_state_lifetime(self.key)

        self.assertIsNone(remaining_ttl_seconds(self._owner_key()))
        self.assertIsNone(memory.get_state_owner(self.key))

    def test_clearing_the_conversation_clears_the_owner_too(self):
        memory.update_climate_budget(self.key, trip_type="beach", owner=5)

        memory.clear_history(self.key)

        self.assertIsNone(memory.get_state_owner(self.key))

    def test_clearing_deletes_the_owner_before_the_state_and_the_history(self):
        memory.update_climate_budget(self.key, trip_type="beach", owner=5)

        deletes = self._mutations_of(lambda: memory.clear_history(self.key))

        self.assertEqual(
            deletes,
            [("delete", "state-owner"), ("delete", "climate-budget"), ("delete", "ownership")],
        )

    def test_the_owner_is_already_invalid_while_a_clear_is_still_tearing_the_state_down(self):
        memory.update_climate_budget(self.key, trip_type="beach", owner=5)
        seen = []

        def look_between_the_two_deletes():
            state = memory.get_climate_budget(self.key)
            seen.append((memory.state_owned_by(self.key, 5), state["trip_type"]))

        hooked = InterleavingCache(cache)
        hooked.after("delete", ":state-owner", look_between_the_two_deletes)

        with mock.patch("ai.memory.cache", hooked):
            memory.clear_history(self.key)

        # Between the two deletes the state is still there, but nobody owns it.
        self.assertEqual(seen, [(False, "beach")])
        self.assertEqual(memory.get_climate_budget(self.key), memory._NO_CLIMATE_BUDGET)


class PendingPromotionLifetimeTests(TestCase):
    def setUp(self):
        self.key = "chat-history:user:lifetime"
        self.pending = memory.new_pending_owner()
        self.owner_key = memory._state_owner_key(self.key)
        self.state_key = memory._climate_budget_key(self.key)
        self.promotion_key = memory._owner_promotion_key(self.key, self.pending)
        self.floor = memory.CONVERSATION_TTL_SECONDS - 60

    def _save_a_promoted_pending_conversation(self, seconds_left=5):
        memory.update_climate_budget(self.key, trip_type="beach", owner=self.pending)
        memory.promote_state_owner(self.key, self.pending, 5)
        for key in (self.owner_key, self.state_key, self.promotion_key):
            cache.touch(key, seconds_left)

    def test_a_refresh_keeps_a_pending_owner_and_its_promotion_alive_together(self):
        self._save_a_promoted_pending_conversation()

        memory.refresh_state_lifetime(self.key)

        for key in (self.owner_key, self.state_key, self.promotion_key):
            self.assertGreater(remaining_ttl_seconds(key), self.floor, key)
        self.assertTrue(memory.state_owned_by(self.key, 5))

    def test_the_turn_bookkeeping_does_the_same(self):
        self._save_a_promoted_pending_conversation()

        memory.append_turn(self.key, user_message="hi", assistant_reply="hello")

        self.assertGreater(remaining_ttl_seconds(self.promotion_key), self.floor)
        self.assertTrue(memory.state_owned_by(self.key, 5))

    def test_a_refresh_never_creates_a_missing_promotion(self):
        memory.update_climate_budget(self.key, trip_type="beach", owner=self.pending)  # unpromoted

        memory.refresh_state_lifetime(self.key)

        self.assertIsNone(remaining_ttl_seconds(self.promotion_key))
        self.assertIsNone(cache.get(self.promotion_key))
        self.assertFalse(memory.state_owned_by(self.key, 5))

    def test_a_promotion_that_really_expired_is_not_resurrected_by_a_refresh(self):
        self._save_a_promoted_pending_conversation(seconds_left=5)
        cache.touch(self.promotion_key, 1)
        time.sleep(1.3)
        self.assertIsNone(cache.get(self.promotion_key))

        memory.refresh_state_lifetime(self.key)

        self.assertIsNone(cache.get(self.promotion_key))
        self.assertIsNone(remaining_ttl_seconds(self.promotion_key))
        # The owner is an orphan now: still present, never honoured, and a
        # refresh doesn't change either of those things.
        self.assertEqual(memory.get_state_owner(self.key), self.pending)
        self.assertFalse(memory.state_owned_by(self.key, 5))
        self.assertFalse(memory.claim_state_for_conversation(self.key, 5))
        self.assertFalse(memory.claim_state_for_conversation(self.key, 6))

    def test_an_integer_owner_needs_no_promotion_record_and_gets_none(self):
        memory.update_climate_budget(self.key, trip_type="beach", owner=5)

        memory.refresh_state_lifetime(self.key)

        self.assertTrue(memory.state_owned_by(self.key, 5))
        self.assertIsNone(remaining_ttl_seconds(self.promotion_key))


class EmptySlotClaimInterleavingTests(TestCase):
    """Another writer gets in at each point of a claim. Whatever happens, the
    claimant must lose without touching that writer's owner or state, and its
    token must never be honoured."""

    def setUp(self):
        self.key = "chat-history:user:claims"
        self.pending = memory.new_pending_owner()

    def _writers(self):
        beach = {"trip_type": "beach"}
        return {
            "unowned": lambda: memory.update_climate_budget(self.key, **beach),
            "pending": lambda: memory.update_climate_budget(self.key, owner=self.pending, **beach),
            "another saved conversation": lambda: memory.update_climate_budget(
                self.key, owner=9, **beach
            ),
        }

    def _claim_with_a_writer_at(self, point, writer):
        hooked = InterleavingCache(cache)
        if point == "before the claim lands":
            hooked.after("get", ":state-owner", writer)
        elif point == "after the claim lands":
            hooked.after("add", ":state-owner", writer)
        else:  # after the state re-check, before the promotion
            hooked.after(
                "add", ":state-owner", lambda: hooked.after("get", ":climate-budget", writer)
            )
        with mock.patch("ai.memory.cache", hooked):
            return memory.claim_empty_state_slot(self.key, 5)

    def test_a_writer_getting_in_at_any_point_defeats_the_claim_without_being_touched(self):
        points = (
            "before the claim lands",
            "after the claim lands",
            "after the re-check",
        )
        for point in points:
            for label, writer in self._writers().items():
                with self.subTest(point=point, writer=label):
                    memory.clear_history(self.key)

                    claimed = self._claim_with_a_writer_at(point, writer)

                    self.assertFalse(claimed)
                    self.assertFalse(memory.state_owned_by(self.key, 5))
                    # The writer's state is intact...
                    self.assertEqual(memory.get_climate_budget(self.key)["trip_type"], "beach")
                    # ...and so is its owner: the claimant never deleted or replaced it.
                    if label == "pending":
                        self.assertEqual(memory.get_state_owner(self.key), self.pending)
                    if label == "another saved conversation":
                        self.assertEqual(memory.get_state_owner(self.key), 9)
                        self.assertTrue(memory.state_owned_by(self.key, 9))
                    # Nobody is handed the slot on the back of the lost claim.
                    self.assertFalse(memory.claim_state_for_conversation(self.key, 6))

    def test_a_lost_claims_token_is_never_honoured_even_if_it_is_left_behind(self):
        # A token left in the owner slot next to someone else's state: nothing
        # vouches for it, so it opens nothing - not for its claimant, not for anyone.
        memory.update_climate_budget(self.key, trip_type="beach")
        token = memory.new_pending_owner()
        cache.set(memory._state_owner_key(self.key), token, memory.CONVERSATION_TTL_SECONDS)

        self.assertFalse(memory.state_owned_by(self.key, 5))
        self.assertFalse(memory.claim_state_for_conversation(self.key, 5))
        self.assertFalse(memory.claim_state_for_conversation(self.key, 6))
        self.assertEqual(memory.get_state_owner(self.key), token)
        self.assertEqual(memory.get_climate_budget(self.key)["trip_type"], "beach")

    def test_a_claim_that_declines_on_sight_changes_nothing(self):
        memory.update_climate_budget(self.key, trip_type="beach", owner=9)
        recorder = InterleavingCache(cache)

        with mock.patch("ai.memory.cache", recorder):
            claimed = memory.claim_empty_state_slot(self.key, 5)

        self.assertFalse(claimed)
        self.assertEqual([op for op, _ in recorder.ops if op in ("set", "add", "delete")], [])

    def test_a_claim_that_loses_the_add_changes_nothing_else(self):
        # The slot looked empty on the first look, but by the time the claim is
        # added somebody owns it.
        cache.set(memory._state_owner_key(self.key), 9, memory.CONVERSATION_TTL_SECONDS)
        hooked = InterleavingCache(cache)
        real_get = hooked.get
        hooked.get = lambda key, *a, **kw: (
            None if key.endswith(":state-owner") else real_get(key, *a, **kw)
        )

        with mock.patch("ai.memory.cache", hooked):
            claimed = memory.claim_empty_state_slot(self.key, 5)

        self.assertFalse(claimed)
        self.assertEqual(memory.get_state_owner(self.key), 9)
        self.assertEqual([op for op, _ in hooked.ops if op in ("set", "delete")], [])

    def test_a_claim_that_wins_with_nobody_around_holds(self):
        self.assertTrue(memory.claim_empty_state_slot(self.key, 5))

        self.assertTrue(memory.state_owned_by(self.key, 5))


class _OrchestrationCase(TestCase):
    def setUp(self):
        make_destination("rome-it", name="Rome", country="Italy", trip_type="culture")
        self.climate = FixedClimateProvider()
        self.user = User.objects.create_user(email="owner@example.com", password="x")
        self.key = memory.conversation_key(user=self.user, session_key=None)
        self.saved = [
            {"role": "user", "content": "saved question"},
            {"role": "assistant", "content": "saved answer"},
        ]

    def _own(self, conversation_id, **state):
        """Seed the shared state as if `conversation_id` had written it."""
        memory.update_climate_budget(self.key, owner=conversation_id, **state)

    def _turn(self, provider, message="a message", **kwargs):
        intent_sink, state_sink = {}, {}
        result = stream_travel_recommendation(
            message,
            user=self.user,
            ai_provider=provider,
            climate_provider=self.climate,
            intent_sink=intent_sink,
            state_sink=state_sink,
            **kwargs,
        )
        "".join(result.reply_chunks)  # consuming the stream is what runs its bookkeeping
        return intent_sink, state_sink

    def _override_turn(self, provider, thread_id, message="a message"):
        return self._turn(provider, message, history_override=self.saved, thread_id=thread_id)


class OverrideTurnOwnershipTests(_OrchestrationCase):
    def _age_the_records(self, seconds=5):
        """Shorten the owner's and the state's clocks so a later refresh shows."""
        cache.touch(memory._state_owner_key(self.key), seconds)
        cache.touch(memory._climate_budget_key(self.key), seconds)

    def _assert_the_clocks_were_left_running(self, seconds=5):
        for key in (memory._state_owner_key(self.key), memory._climate_budget_key(self.key)):
            self.assertLessEqual(remaining_ttl_seconds(key), seconds, key)

    def test_no_thread_id_keeps_todays_stateless_behavior_even_if_something_owns_the_state(self):
        self._own(5, min_temp_c=20, trip_type="culture")
        self._age_the_records()
        owner_before = memory.get_state_owner(self.key)
        state_before = memory.get_climate_budget(self.key)
        history_before = memory.get_history(self.key)
        spy = StateWriteSpy(cache)

        with mock.patch("ai.memory.cache", spy):
            intent_sink, state_sink = self._override_turn(ScriptedProvider([_t()]), None)

        self.assertIsNone(intent_sink["min_temp_c"])  # didn't inherit the state
        self.assertEqual(state_sink, {})
        self.assertEqual(spy.state_writes, [])
        self.assertEqual(memory.get_state_owner(self.key), owner_before)
        self.assertEqual(memory.get_climate_budget(self.key), state_before)
        self.assertEqual(memory.get_history(self.key), history_before)
        # Not even its lifetime is this turn's to extend.
        self._assert_the_clocks_were_left_running()

    def test_no_thread_id_does_not_claim_an_empty_slot_either(self):
        intent_sink, state_sink = self._override_turn(
            ScriptedProvider([_t({"trip_type": "culture"}, {"min_temp_c": 20})]), None
        )

        self.assertEqual(state_sink, {})
        self.assertIsNone(memory.get_state_owner(self.key))
        self.assertEqual(memory.get_climate_budget(self.key), memory._NO_CLIMATE_BUDGET)

    def test_only_a_saved_conversation_id_can_use_state_with_an_override(self):
        self._own(5, min_temp_c=20)
        for bad in (memory.new_pending_owner(), "5", True, 5.0):
            with self.subTest(thread_id=bad):
                _, state_sink = self._override_turn(ScriptedProvider([_t()]), bad)
                self.assertEqual(state_sink, {})
                self.assertEqual(memory.get_state_owner(self.key), 5)

    def test_the_owning_conversation_uses_the_state_and_keeps_its_ownership(self):
        self._own(5, min_temp_c=20, trip_type="culture")
        provider = ScriptedProvider([_t({}, {"max_cost_of_living": 2})])

        intent_sink, state_sink = self._override_turn(provider, 5)

        self.assertEqual(intent_sink["min_temp_c"], 20)  # carried over
        self.assertEqual(intent_sink["trip_type"], "culture")
        self.assertEqual(intent_sink["max_cost_of_living"], 2)  # plus this turn's own
        self.assertEqual(state_sink["min_temp_c"], 20)
        self.assertEqual(state_sink["max_cost_of_living"], 2)
        self.assertEqual(memory.get_state_owner(self.key), 5)

    def test_the_history_the_ai_sees_still_comes_from_the_override_not_redis(self):
        memory.append_turn(self.key, user_message="redis question", assistant_reply="redis answer")
        self._own(5, min_temp_c=20)
        provider = ScriptedProvider([_t()])

        self._override_turn(provider, 5)

        seen = [m.content for m in provider.intent_messages[0]]
        self.assertIn("saved question", seen)
        self.assertNotIn("redis question", seen)
        # ...and Redis history is left as it was: the saved copy owns the text.
        self.assertEqual(
            [m["content"] for m in memory.get_history(self.key)], ["redis question", "redis answer"]
        )

    def test_another_conversations_state_is_neither_read_nor_mutated(self):
        self._own(6, min_temp_c=20, trip_type="culture")
        self._age_the_records()
        state_before = memory.get_climate_budget(self.key)
        spy = StateWriteSpy(cache)

        with mock.patch("ai.memory.cache", spy):
            intent_sink, state_sink = self._override_turn(
                ScriptedProvider([_t({}, {"max_cost_of_living": 2})]), 5
            )

        self.assertIsNone(intent_sink["min_temp_c"])
        self.assertEqual(intent_sink["max_cost_of_living"], 2)  # only this turn's own
        self.assertEqual(state_sink, {})
        self.assertEqual(spy.state_writes, [])
        self.assertEqual(memory.get_state_owner(self.key), 6)
        self.assertEqual(memory.get_climate_budget(self.key), state_before)
        self._assert_the_clocks_were_left_running()

    def test_a_missing_owner_with_existing_state_fails_closed(self):
        memory.update_climate_budget(self.key, min_temp_c=20, trip_type="culture")  # unowned
        state_before = memory.get_climate_budget(self.key)

        intent_sink, state_sink = self._override_turn(
            ScriptedProvider([_t({}, {"max_cost_of_living": 2})]), 5
        )

        self.assertIsNone(intent_sink["min_temp_c"])
        self.assertEqual(state_sink, {})
        self.assertIsNone(memory.get_state_owner(self.key))  # nothing was claimed
        self.assertEqual(memory.get_climate_budget(self.key), state_before)

    def test_an_empty_slot_is_claimed_and_the_conversation_starts_blank(self):
        provider = ScriptedProvider([_t({"trip_type": "culture"}, {"min_temp_c": 20}), _t()])

        first_intent, first_state = self._override_turn(provider, 5)
        second_intent, second_state = self._override_turn(provider, 5)

        self.assertEqual(memory.get_state_owner(self.key), 5)
        self.assertEqual(first_state["min_temp_c"], 20)  # only what this turn said
        self.assertEqual(second_intent["min_temp_c"], 20)  # and it accumulates from here on
        self.assertEqual(second_state["trip_type"], "culture")

    def test_redis_expiry_then_a_continuation_adopts_the_empty_slot(self):
        self._own(5, min_temp_c=20)
        for k in (
            self.key,
            memory._climate_budget_key(self.key),
            memory._state_owner_key(self.key),
        ):
            cache.delete(k)  # what the TTL (or a Redis restart) does
        provider = ScriptedProvider([_t({}, {"max_cost_of_living": 2}), _t()])

        first_intent, _ = self._override_turn(provider, 5)
        second_intent, _ = self._override_turn(provider, 5)

        self.assertIsNone(first_intent["min_temp_c"])  # the old state is gone, not reconstructed
        self.assertEqual(second_intent["max_cost_of_living"], 2)  # new state accumulates
        self.assertEqual(memory.get_state_owner(self.key), 5)

    def test_ownership_lost_while_the_turn_was_in_flight_is_never_written_over(self):
        self._own(5, min_temp_c=20)
        provider = ScriptedProvider([_t({}, {"min_temp_c": 18})])

        def another_tab_takes_the_state(schema_name):
            if schema_name == "climate_budget_signal":
                memory.update_climate_budget(self.key, min_temp_c=99)  # unowned write

        provider.before_call = another_tab_takes_the_state

        intent_sink, state_sink = self._override_turn(provider, 5)

        self.assertEqual(intent_sink["min_temp_c"], 18)  # this turn ran on its own values
        self.assertEqual(memory.get_climate_budget(self.key)["min_temp_c"], 99)  # theirs, intact
        self.assertIsNone(memory.get_state_owner(self.key))  # and not re-stamped as ours
        # The state now in Redis is somebody else's, so it isn't reported as this turn's.
        self.assertEqual(state_sink, {})

    def test_ownership_lost_to_another_saved_conversation_mid_turn_reports_no_state(self):
        self._own(5, min_temp_c=20)
        provider = ScriptedProvider([_t({}, {"min_temp_c": 18})])
        provider.before_call = lambda schema_name: (
            schema_name == "climate_budget_signal" and self._own(6, min_temp_c=99)
        )

        _, state_sink = self._override_turn(provider, 5)

        self.assertEqual(state_sink, {})
        self.assertEqual(memory.get_state_owner(self.key), 6)
        self.assertEqual(memory.get_climate_budget(self.key)["min_temp_c"], 99)

    def test_an_owned_turn_that_returns_early_still_keeps_the_lifetime_in_step(self):
        self._own(5, min_temp_c=20)
        cache.touch(memory._state_owner_key(self.key), 5)
        cache.touch(memory._climate_budget_key(self.key), 5)
        history_before = memory.get_history(self.key)

        self._override_turn(ScriptedProvider([{"intent": intent(message_type="off_topic")}]), 5)

        floor = memory.CONVERSATION_TTL_SECONDS - 60
        self.assertGreater(remaining_ttl_seconds(memory._state_owner_key(self.key)), floor)
        self.assertGreater(remaining_ttl_seconds(memory._climate_budget_key(self.key)), floor)
        self.assertEqual(memory.get_history(self.key), history_before)
        self.assertEqual(memory.get_climate_budget(self.key)["min_temp_c"], 20)  # untouched

    def test_state_sink_reports_the_state_the_request_was_built_from(self):
        self._own(5, min_temp_c=20, trip_type="culture")

        intent_sink, state_sink = self._override_turn(
            ScriptedProvider([_t({}, {"max_temp_c": 30})]), 5
        )

        for field in memory._NO_CLIMATE_BUDGET:
            self.assertEqual(state_sink[field], intent_sink[field], field)

    def test_model_calls_are_the_same_whether_or_not_the_state_is_used(self):
        self._own(5, min_temp_c=20)
        owned = ScriptedProvider([_t()])
        self._override_turn(owned, 5)
        stateless = ScriptedProvider([_t()])
        self._override_turn(stateless, None)

        for provider in (owned, stateless):
            self.assertEqual(provider.structured_calls, _MERGE_PATH_CALLS)
            self.assertEqual((provider.reply_calls, provider.stream_calls), (0, 1))


class RedisPathStampingTests(_OrchestrationCase):
    def test_a_turn_on_the_redis_path_stamps_the_thread_it_was_given(self):
        pending = memory.new_pending_owner()

        _, state_sink = self._turn(
            ScriptedProvider([_t({"trip_type": "culture"}, {"min_temp_c": 20})]), thread_id=pending
        )

        self.assertEqual(memory.get_state_owner(self.key), pending)
        self.assertEqual(state_sink["min_temp_c"], 20)

    def test_an_untracked_turn_clears_whoever_owned_the_state(self):
        self._own(5, min_temp_c=20)

        self._turn(ScriptedProvider([_t({}, {"max_cost_of_living": 2})]), thread_id=None)

        self.assertIsNone(memory.get_state_owner(self.key))
        self.assertEqual(memory.get_climate_budget(self.key)["max_cost_of_living"], 2)

    def test_feedback_exclusions_follow_the_same_ownership_rule(self):
        self._own(5, min_temp_c=20)
        feedback = {"message_type": "feedback", "excluded_place_names": ["Paris"]}

        # An untracked Redis-path write clears the owner...
        self._turn(ScriptedProvider([{"intent": intent(**feedback)}]), thread_id=None)
        self.assertIsNone(memory.get_state_owner(self.key))
        # ...and an owning override turn keeps it.
        self._own(5, min_temp_c=20)
        self._override_turn(ScriptedProvider([{"intent": intent(**feedback)}]), 5)
        self.assertEqual(memory.get_state_owner(self.key), 5)
        self.assertIn("Paris", memory.get_climate_budget(self.key)["excluded_place_names"])
