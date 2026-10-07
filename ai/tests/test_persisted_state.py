"""stream_travel_recommendation()'s state_sink: the accumulated traveler
state as it's persisted after a turn, reported independently of
intent_sink (which is only what that one message's extraction yielded).
"""

from unittest import mock

from django.core.cache import cache
from django.test import TestCase

from ai import memory
from ai.orchestration import stream_travel_recommendation
from ai.tests.helpers import (
    FixedClimateProvider,
    ScriptedProvider,
    StateWriteSpy,
    intent,
    make_destination,
    remaining_ttl_seconds,
)

_MERGE_PATH_CALLS = ["travel_message", "climate_budget_signal", "traveler_state_clear_signal"]

_ITALY_TURN = {
    "intent": intent(trip_type="culture", country="Italy"),
    "climate_budget": {"max_cost_of_living": 2},
}


class _StateSinkTestCase(TestCase):
    def setUp(self):
        make_destination("rome-it", name="Rome", country="Italy", trip_type="culture")
        self.climate = FixedClimateProvider()

    def _turn(self, provider, message="hello", *, session="s1", **kwargs):
        result = stream_travel_recommendation(
            message,
            session_key=session,
            ai_provider=provider,
            climate_provider=self.climate,
            **kwargs,
        )
        # Consuming the stream is what runs the reply generator's own
        # bookkeeping (the history append) - a real request always does.
        reply = "".join(result.reply_chunks)
        return result, reply

    def _key(self, session="s1"):
        return memory.conversation_key(user=None, session_key=session)


class RawExtractionVersusPersistedStateTests(_StateSinkTestCase):
    def test_off_topic_turn_exposes_the_previously_persisted_state(self):
        provider = ScriptedProvider([_ITALY_TURN, {"intent": intent(message_type="off_topic")}])
        self._turn(provider, "quero cultura na Itália, barato")

        intent_sink, state_sink = {}, {}
        self._turn(
            provider, "meu chefe está de férias", intent_sink=intent_sink, state_sink=state_sink
        )

        # Raw extraction of the aside is empty...
        self.assertEqual(intent_sink["message_type"], "off_topic")
        self.assertIsNone(intent_sink["trip_type"])
        self.assertIsNone(intent_sink["country"])
        # ...and that doesn't say anything about what the conversation holds.
        self.assertEqual(state_sink["trip_type"], "culture")
        self.assertEqual(state_sink["country"], "Italy")
        self.assertEqual(state_sink["max_cost_of_living"], 2)

    def test_state_sink_carries_the_same_seven_fields_the_accumulator_does(self):
        provider = ScriptedProvider([{"intent": intent(message_type="off_topic")}])
        state_sink = {}

        self._turn(provider, "hi", state_sink=state_sink)

        self.assertEqual(set(state_sink), set(memory._NO_CLIMATE_BUDGET))

    def test_merge_path_state_sink_matches_the_state_the_request_was_built_from(self):
        provider = ScriptedProvider([_ITALY_TURN])
        intent_sink, state_sink = {}, {}

        self._turn(provider, "cultura na Itália", intent_sink=intent_sink, state_sink=state_sink)

        for field in memory._NO_CLIMATE_BUDGET:
            self.assertEqual(state_sink[field], intent_sink[field], field)

    def test_state_sink_is_a_copy_of_the_blank_default_not_the_shared_object(self):
        provider = ScriptedProvider([{"intent": intent(message_type="off_topic")}])
        state_sink = {}
        self._turn(provider, "hi", state_sink=state_sink)

        state_sink["excluded_place_names"].append("Paris")

        self.assertEqual(memory._NO_CLIMATE_BUDGET["excluded_place_names"], [])

    def test_nothing_is_reported_when_nothing_is_persisted(self):
        # A resumed saved conversation has no Redis session to persist into.
        provider = ScriptedProvider([_ITALY_TURN])
        state_sink = {}

        stream_travel_recommendation(
            "cultura na Itália",
            session_key="s1",
            history_override=[],
            ai_provider=provider,
            climate_provider=self.climate,
            state_sink=state_sink,
        )

        self.assertEqual(state_sink, {})


class IrrelevantMentionsDoNotOverwriteStateTests(_StateSinkTestCase):
    """Whatever the combined call happened to extract from an aside, a turn
    that returns before the accumulator merge never persists it."""

    # (label, intent fields for the second turn). Each carries a country
    # that isn't the traveler's own - someone else's wish, a recalled place.
    ASIDES = (
        ("off_topic", dict(message_type="off_topic", country="Peru")),
        (
            "future_intent",
            dict(message_type="future_intent", country="Peru", future_destination_name="Peru"),
        ),
        ("recall", dict(is_recall_request=True, country="Peru")),
    )

    def setUp(self):
        super().setUp()
        # A real catalog country, so the aside's extraction survives
        # validation the way it does in the wild (an unknown one would be
        # nulled out before it ever got near the state).
        make_destination("cusco-pe", name="Cusco", country="Peru", trip_type="culture")

    def test_another_persons_country_does_not_overwrite_the_persisted_country(self):
        for label, aside_fields in self.ASIDES:
            with self.subTest(branch=label):
                session = f"aside-{label}"
                provider = ScriptedProvider([_ITALY_TURN, {"intent": intent(**aside_fields)}])
                self._turn(provider, "cultura na Itália", session=session)

                intent_sink, state_sink = {}, {}
                self._turn(
                    provider,
                    "minha mãe sempre quis conhecer o Peru, mas a viagem é só minha",
                    session=session,
                    intent_sink=intent_sink,
                    state_sink=state_sink,
                )

                self.assertEqual(intent_sink["country"], "Peru")  # it really was extracted
                self.assertEqual(state_sink["country"], "Italy")  # and it went nowhere
                self.assertEqual(memory.get_climate_budget(self._key(session))["country"], "Italy")

    def test_the_next_search_still_uses_the_travelers_own_country(self):
        provider = ScriptedProvider(
            [
                _ITALY_TURN,
                {"intent": intent(message_type="off_topic", country="Peru")},
                {"intent": intent()},  # a plain follow-up that restates nothing
            ]
        )
        self._turn(provider, "cultura na Itália")
        self._turn(provider, "minha mãe quer conhecer o Peru")

        result, _ = self._turn(provider, "quais lugares você recomenda?")

        self.assertEqual([s.destination.slug for s in result.recommendations], ["rome-it"])

    def test_feedback_still_persists_exclusions_and_nothing_else(self):
        provider = ScriptedProvider(
            [
                _ITALY_TURN,
                {
                    "intent": intent(
                        message_type="feedback",
                        feedback_destination_name="Tokyo",
                        excluded_place_names=["Tokyo"],
                        country="Japan",
                    )
                },
            ]
        )
        self._turn(provider, "cultura na Itália")

        state_sink = {}
        self._turn(provider, "já fui a Tóquio, não quero repetir", state_sink=state_sink)

        self.assertEqual(state_sink["excluded_place_names"], ["Tokyo"])
        self.assertEqual(state_sink["country"], "Italy")


class StateLifetimeThroughTurnsTests(_StateSinkTestCase):
    def test_early_return_turns_keep_the_states_lifetime_in_step_with_history(self):
        provider = ScriptedProvider(
            [
                _ITALY_TURN,
                {"intent": intent(message_type="off_topic")},
                {"intent": intent(is_recall_request=True)},
            ]
        )
        self._turn(provider, "cultura na Itália")
        state_key = memory._climate_budget_key(self._key())
        # As if the merge turn were now old: the state's own clock is nearly out.
        cache.touch(state_key, 5)

        self._turn(provider, "meu chefe está de férias")
        self._turn(provider, "o que você tinha sugerido?")

        state_ttl = remaining_ttl_seconds(state_key)
        self.assertGreater(state_ttl, memory.CONVERSATION_TTL_SECONDS - 60)
        self.assertAlmostEqual(state_ttl, remaining_ttl_seconds(self._key()), delta=5)


class UnchangedMergePathSemanticsTests(_StateSinkTestCase):
    def test_set_unchanged_and_clear_still_work_across_merge_path_turns(self):
        provider = ScriptedProvider(
            [
                _ITALY_TURN,
                # UNCHANGED: says nothing about country.
                {"intent": intent()},
                # CLEAR: the isolated clear signal, no new value.
                {"intent": intent(), "state_clear": {"country_cleared": True}},
                # SET: a new value replaces whatever was there.
                {"intent": intent(country="Italy")},
            ]
        )
        states = []
        for message in ("cultura na Itália", "e então?", "esquece o país", "na Itália mesmo"):
            state_sink = {}
            self._turn(provider, message, state_sink=state_sink)
            states.append(state_sink)

        self.assertEqual([s["country"] for s in states], ["Italy", "Italy", None, "Italy"])
        self.assertEqual({s["trip_type"] for s in states}, {"culture"})  # never touched
        self.assertEqual({s["max_cost_of_living"] for s in states}, {2})

    def test_results_are_identical_with_and_without_the_sinks(self):
        def run(session, **sinks):
            provider = ScriptedProvider([_ITALY_TURN, {"intent": intent()}])
            first, first_reply = self._turn(provider, "cultura na Itália", session=session, **sinks)
            second, second_reply = self._turn(provider, "e então?", session=session, **sinks)
            return (
                [s.destination.slug for s in first.recommendations],
                first_reply,
                [s.destination.slug for s in second.recommendations],
                second_reply,
            )

        self.assertEqual(run("plain"), run("observed", intent_sink={}, state_sink={}))


class NoAdditionalModelCallsTests(_StateSinkTestCase):
    def _counts(self, provider):
        return (list(provider.structured_calls), provider.reply_calls, provider.stream_calls)

    def test_state_sink_adds_no_model_calls_on_any_path(self):
        script = [
            _ITALY_TURN,
            {"intent": intent(message_type="off_topic")},
            {"intent": intent(is_recall_request=True)},
            {"intent": intent(message_type="future_intent", future_destination_name="Peru")},
        ]

        def run(session, **sinks):
            provider = ScriptedProvider(script)
            for message in ("a", "b", "c", "d"):
                self._turn(provider, message, session=session, **sinks)
            return self._counts(provider)

        without_sink = run("no-sink")
        with_sink = run("with-sink", state_sink={})

        self.assertEqual(without_sink, with_sink)

    def test_per_path_call_counts_are_the_established_ones(self):
        # Merge path: combined intent + the two isolated extractions + the
        # explanation stream. An early-return path: the combined intent
        # call and its own reply, nothing else.
        merge = ScriptedProvider([_ITALY_TURN])
        self._turn(merge, "cultura na Itália", state_sink={})
        self.assertEqual(self._counts(merge), (_MERGE_PATH_CALLS, 0, 1))

        off_topic = ScriptedProvider([{"intent": intent(message_type="off_topic")}])
        self._turn(off_topic, "hi", session="other", state_sink={})
        self.assertEqual(self._counts(off_topic), (["travel_message"], 0, 1))


def _t(intent_fields=None, climate=None, clear=None):
    return {
        "intent": intent(**(intent_fields or {})),
        "climate_budget": climate or {},
        "state_clear": clear or {},
    }


_ITALY = {"trip_type": "culture", "country": "Italy"}


class ResolvedTemperatureRangeThroughTurnsTests(_StateSinkTestCase):
    """The temperature pair is reconciled inside the merge, so for every
    merge-path turn the state the request is built from, the state that's
    stored, and the state state_sink reports are one and the same."""

    def _play(self, script, *, session="contra"):
        provider = ScriptedProvider(script)
        spy = StateWriteSpy(cache)
        turns = []
        with mock.patch("ai.memory.cache", spy):
            for n in range(len(script)):
                intent_sink, state_sink = {}, {}
                self._turn(
                    provider,
                    f"message {chr(ord('a') + n)}",
                    session=session,
                    intent_sink=intent_sink,
                    state_sink=state_sink,
                )
                turns.append((intent_sink, state_sink))
        return turns, spy, provider

    def _range(self, snapshot):
        return (snapshot["min_temp_c"], snapshot["max_temp_c"])

    def _assert_request_equals_persisted(self, intent_sink, state_sink):
        for field in memory._NO_CLIMATE_BUDGET:
            self.assertEqual(state_sink[field], intent_sink[field], field)

    def _assert_ranges(self, turns, spy, expected, *, session="contra"):
        for n, (intent_sink, state_sink) in enumerate(turns):
            with self.subTest(turn=n + 1):
                self.assertEqual(self._range(intent_sink), expected[n])  # what the request used
                self.assertEqual(self._range(state_sink), expected[n])  # what's persisted
                self._assert_request_equals_persisted(intent_sink, state_sink)
        self.assertEqual(memory.get_climate_budget(self._key(session)), turns[-1][1])
        self.assertEqual(spy.contradictory_writes(), [])

    def test_hot_then_cold_then_an_unrelated_turn(self):
        turns, spy, _ = self._play(
            [_t(_ITALY, {"min_temp_c": 28}), _t(None, {"max_temp_c": 15}), _t()]
        )

        self._assert_ranges(turns, spy, [(28, None), (None, 15), (None, 15)])

    def test_cold_then_hot_then_an_unrelated_turn(self):
        turns, spy, _ = self._play(
            [_t(_ITALY, {"max_temp_c": 15}), _t(None, {"min_temp_c": 28}), _t()]
        )

        self._assert_ranges(turns, spy, [(None, 15), (28, None), (28, None)])

    def test_hot_then_an_explicit_clear_then_an_unrelated_turn(self):
        turns, spy, _ = self._play(
            [
                _t(_ITALY, {"min_temp_c": 28}),
                _t(None, {}, {"min_temp_c_cleared": True}),
                _t(),
            ]
        )

        self._assert_ranges(turns, spy, [(28, None), (None, None), (None, None)])

    def test_cold_then_an_explicit_clear_then_an_unrelated_turn(self):
        turns, spy, _ = self._play(
            [
                _t(_ITALY, {"max_temp_c": 15}),
                _t(None, {}, {"max_temp_c_cleared": True}),
                _t(),
            ]
        )

        self._assert_ranges(turns, spy, [(None, 15), (None, None), (None, None)])

    def test_non_contradictory_min_and_max_are_left_alone(self):
        turns, spy, _ = self._play(
            [_t(_ITALY, {"min_temp_c": 20}), _t(None, {"max_temp_c": 30}), _t()]
        )

        self._assert_ranges(turns, spy, [(20, None), (20, 30), (20, 30)])

    def test_min_equal_to_max_is_kept(self):
        turns, spy, _ = self._play(
            [_t(_ITALY, {"min_temp_c": 20}), _t(None, {"max_temp_c": 20}), _t()]
        )

        self._assert_ranges(turns, spy, [(20, None), (20, 20), (20, 20)])

    def test_an_early_return_turn_after_a_resolved_contradiction_reports_the_resolved_state(self):
        script = [
            _t(_ITALY, {"min_temp_c": 28}),
            _t(None, {"max_temp_c": 15}),
            {"intent": intent(message_type="off_topic")},
            _t(),
        ]
        turns, spy, _ = self._play(script)

        self.assertEqual(self._range(turns[2][0]), (None, None))  # the aside's own extraction
        self.assertEqual(self._range(turns[2][1]), (None, 15))  # what the conversation still holds
        self.assertEqual(self._range(turns[3][0]), (None, 15))  # and what the next search uses
        self.assertEqual(spy.contradictory_writes(), [])

    def test_geography_and_exclusions_are_unaffected(self):
        turns, spy, _ = self._play(
            [
                _t({**_ITALY, "excluded_place_names": ["Paris"]}, {"min_temp_c": 28}),
                _t(None, {"max_temp_c": 15}),
                _t(),
            ]
        )

        for n, (intent_sink, state_sink) in enumerate(turns):
            with self.subTest(turn=n + 1):
                self.assertEqual(state_sink["trip_type"], "culture")
                self.assertEqual(state_sink["country"], "Italy")
                self.assertEqual(state_sink["excluded_place_names"], ["Paris"])
                self._assert_request_equals_persisted(intent_sink, state_sink)
        self.assertEqual(spy.contradictory_writes(), [])

    def test_a_contradiction_turn_makes_no_additional_model_calls(self):
        turns, _, provider = self._play(
            [_t(_ITALY, {"min_temp_c": 28}), _t(None, {"max_temp_c": 15}), _t()]
        )

        self.assertEqual(provider.structured_calls, _MERGE_PATH_CALLS * 3)
        self.assertEqual((provider.reply_calls, provider.stream_calls), (0, 3))
