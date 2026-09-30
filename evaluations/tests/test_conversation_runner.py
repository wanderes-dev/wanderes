from django.test import TestCase

from ai import memory
from ai.provider.base import AIResponse
from ai.tests.helpers import FixedClimateProvider, ScriptedProvider, intent, make_destination
from evaluations.conversation_runner import run_conversation, select_conversations
from evaluations.conversation_scenarios import ConversationScenario, ConversationTurn
from evaluations.cost import CostTracker
from evaluations.weather_fixtures import MissingWeatherFixtureError
from integrations.climate.base import MonthlyClimateSummary
from travel.models import Destination


class _StubProvider:
    """Returns a fixed structured reply per schema name, and a plain reply
    for the final explanation - just enough to drive
    stream_travel_recommendation() through a real conversation without a
    live API. Deliberately dumb (same intent every call) - the runner
    tests below only need to confirm mechanics (session persistence,
    checkpoint wiring, error handling), not real conversational
    intelligence."""

    def __init__(
        self,
        intent: dict,
        climate_budget: dict | None = None,
        reply_text: str = "Beachtown is a great pick.",
    ):
        self.intent = intent
        # Defaults to mirroring intent's own trip_type/continent/country/
        # excluded_place_names, not just the three original climate/budget
        # fields - the isolated state-delta call now covers all seven, and
        # a fixed all-None default here would wipe trip_type on every
        # turn via the real Redis accumulator these tests deliberately
        # exercise (see test_real_redis_backed_state_persists...).
        self.climate_budget = climate_budget or {
            "min_temp_c": None,
            "max_temp_c": None,
            "max_cost_of_living": None,
            "trip_type": intent.get("trip_type"),
            "continent": intent.get("continent"),
            "country": intent.get("country"),
            "excluded_place_names_add": intent.get("excluded_place_names") or [],
        }
        self.reply_text = reply_text
        self.calls = []

    def generate_structured_reply(
        self, messages, *, json_schema, max_tokens=None, temperature=None
    ):
        self.calls.append(json_schema["name"])
        if json_schema["name"] == "climate_budget_signal":
            return self.climate_budget
        return self.intent

    def generate_reply(self, messages, *, max_tokens=None):
        return AIResponse(
            content=self.reply_text, model="stub", prompt_tokens=0, completion_tokens=0
        )

    def stream_reply(self, messages, *, max_tokens=None, temperature=None):
        for word in self.reply_text.split(" "):
            yield word + " "


_BASE_INTENT = {
    "message_type": "recommendation",
    "month": None,
    "min_temp_c": None,
    "max_temp_c": None,
    "max_cost_of_living": None,
    "trip_type": "beach",
    "continent": None,
    "country": None,
    "excluded_place_names": [],
    "feedback_destination_name": None,
    "feedback_rating": None,
    "feedback_tags": [],
    "feedback_comment": None,
    "future_destination_name": None,
    "is_recall_request": False,
    "is_visa_or_entry_question": False,
    "visa_question_country": None,
    "visa_question_nationality": None,
    "is_booking_request": False,
    "is_video_request": False,
    "video_place_name": None,
    "is_activity_question": False,
    "activity_place_name": None,
    "is_accommodation_request": False,
    "accommodation_place_name": None,
    "accommodation_party_size": None,
}


def _make_destination(slug, **kwargs):
    defaults = dict(
        name="Beachtown",
        country="Testland",
        latitude=10.0,
        longitude=10.0,
        trip_type="beach",
        cost_of_living=2,
        best_season="x",
        worst_season="x",
        short_description="x",
        points_of_interest=[],
    )
    defaults.update(kwargs)
    return Destination.objects.create(slug=slug, **defaults)


def _conversation(*, turns):
    return ConversationScenario(id="TEST-CONV", split="dev", family="drift", turns=tuple(turns))


class _AlwaysSucceedsClimateProvider:
    """A trivial stub - real weather data isn't the point of these tests,
    only whether the runner correctly wires turns/checkpoints/session
    state through the real orchestration entry point."""

    def get_monthly_climate(self, *, latitude, longitude, month, year=None):
        return MonthlyClimateSummary(2025, month, 28.0, 20.0, 5.0)

    def __bool__(self):
        return True


class RunConversationMechanicsTests(TestCase):
    def setUp(self):
        self.destination = _make_destination("beach-1")
        self.climate_provider = _AlwaysSucceedsClimateProvider()

    def test_two_turns_share_the_same_session_and_both_get_scored(self):
        provider = _StubProvider(dict(_BASE_INTENT))
        conversation = _conversation(
            turns=[
                ConversationTurn(message="quero uma praia", expected_state={"trip_type": "beach"}),
                ConversationTurn(message="algo mais?", expected_state={"trip_type": "beach"}),
            ]
        )
        result = run_conversation(
            conversation,
            ai_provider=provider,
            climate_provider=self.climate_provider,
            cost=CostTracker("stub"),
        )
        self.assertEqual(len(result.turns), 2)
        self.assertTrue(result.turns[0].checkpoint.all_match)
        self.assertTrue(result.turns[1].checkpoint.all_match)
        self.assertTrue(result.passed)

    def test_checkpoint_mismatch_fails_the_conversation(self):
        provider = _StubProvider({**_BASE_INTENT, "trip_type": "city"})
        conversation = _conversation(
            turns=[
                ConversationTurn(message="quero uma praia", expected_state={"trip_type": "beach"}),
                ConversationTurn(message="algo mais?"),
            ]
        )
        result = run_conversation(
            conversation,
            ai_provider=provider,
            climate_provider=self.climate_provider,
            cost=CostTracker("stub"),
        )
        self.assertFalse(result.turns[0].checkpoint.all_match)
        self.assertFalse(result.passed)
        self.assertIn("checkpoint_state:trip_type", result.failed_check_names())

    def test_missing_weather_fixture_is_an_infrastructure_failure_not_a_quality_failure(self):
        provider = _StubProvider({**_BASE_INTENT, "country": "Nowhereland"})
        conversation = _conversation(
            turns=[
                ConversationTurn(message="a", expected_state={"country": "Nowhereland"}),
                ConversationTurn(message="b"),
            ]
        )

        class _AlwaysMissingClimateProvider:
            def get_monthly_climate(self, **kwargs):
                raise MissingWeatherFixtureError(1.0, 1.0, 1)

            def __bool__(self):
                return True

        result = run_conversation(
            conversation,
            ai_provider=provider,
            climate_provider=_AlwaysMissingClimateProvider(),
            cost=CostTracker("stub"),
        )
        self.assertTrue(result.is_infrastructure_failure)
        self.assertFalse(result.passed)
        self.assertEqual(result.failed_check_names(), ["dependency_failure"])

    def test_real_redis_backed_state_persists_across_turns_via_session_key(self):
        """The one claim this whole framework's fidelity rests on: driving
        turns through session_key= (never history_override=) really does
        exercise ai.memory's own Redis-backed conversation key, the same
        way a live /chat/ request does."""
        provider = _StubProvider(dict(_BASE_INTENT))
        conversation = _conversation(
            turns=[
                ConversationTurn(message="turn one"),
                ConversationTurn(message="turn two"),
            ]
        )
        run_conversation(
            conversation,
            ai_provider=provider,
            climate_provider=self.climate_provider,
            cost=CostTracker("stub"),
        )
        conv_key = memory.conversation_key(user=None, session_key="eval-conv-TEST-CONV-0")
        history = memory.get_history(conv_key)
        # Both turns' (user, assistant) pairs should have been appended for
        # real - 4 messages, not 0 (which is what history_override's
        # conv_key=None no-op _remember would have left behind).
        self.assertEqual(len(history), 4)
        self.assertEqual(history[0]["content"], "turn one")
        self.assertEqual(history[2]["content"], "turn two")


class CheckpointsReadPersistedStateTests(TestCase):
    """Checkpoints assert on the state the conversation holds after a turn
    (ai.orchestration's state_sink), not on what that one message's
    extraction happened to yield."""

    def setUp(self):
        make_destination("rome-it", name="Rome", country="Italy", trip_type="culture")
        self.climate_provider = FixedClimateProvider()

    def _run(self, turns, script):
        return run_conversation(
            _conversation(turns=turns),
            ai_provider=ScriptedProvider(script),
            climate_provider=self.climate_provider,
            cost=CostTracker("stub"),
        )

    def test_a_turn_that_returns_before_the_merge_still_reports_the_held_state(self):
        result = self._run(
            [
                ConversationTurn(
                    message="cultura na Itália",
                    expected_state={"trip_type": "culture", "country": "Italy"},
                ),
                ConversationTurn(
                    message="meu chefe está de férias",
                    expected_state={"trip_type": "culture", "country": "Italy"},
                    expected_transitions={"trip_type": "retained", "country": "retained"},
                ),
            ],
            [
                {"intent": intent(trip_type="culture", country="Italy")},
                {"intent": intent(message_type="off_topic")},
            ],
        )

        aside = result.turns[1]
        self.assertIsNone(aside.intent["trip_type"])  # the raw extraction was empty
        self.assertEqual(aside.effective_state["trip_type"], "culture")
        self.assertEqual(aside.effective_state["country"], "Italy")
        self.assertTrue(aside.checkpoint.all_match)
        self.assertEqual(result.lost_context_findings, [])
        self.assertTrue(result.passed)

    def test_extraction_that_was_never_persisted_does_not_satisfy_a_checkpoint(self):
        # A stated future trip is extracted correctly but returns before the
        # merge, so nothing is held for the next turn. Reading the raw
        # extraction used to make this look fine.
        result = self._run(
            [
                ConversationTurn(
                    message="quero conhecer a Itália", expected_state={"country": "Italy"}
                ),
                ConversationTurn(message="obrigado"),
            ],
            [
                {"intent": intent(message_type="future_intent", country="Italy")},
                {"intent": intent(message_type="off_topic")},
            ],
        )

        turn = result.turns[0]
        self.assertEqual(turn.intent["country"], "Italy")  # extracted...
        self.assertIsNone(turn.effective_state["country"])  # ...not persisted
        self.assertFalse(turn.checkpoint.all_match)
        self.assertIn("checkpoint_state:country", result.failed_check_names())

    def test_month_is_still_read_from_the_turns_own_extraction(self):
        result = self._run(
            [
                ConversationTurn(message="em novembro", expected_state={"month": 11}),
                ConversationTurn(message="obrigado"),
            ],
            [
                {"intent": intent(trip_type="culture", country="Italy", month=11)},
                {"intent": intent(message_type="off_topic")},
            ],
        )

        self.assertTrue(result.turns[0].checkpoint.all_match)

    def test_effective_state_is_written_to_the_turn_json(self):
        result = self._run(
            [ConversationTurn(message="cultura na Itália"), ConversationTurn(message="obrigado")],
            [
                {"intent": intent(trip_type="culture", country="Italy")},
                {"intent": intent(message_type="off_topic")},
            ],
        )

        turn_json = result.turns[0].to_json()
        self.assertEqual(turn_json["effective_state"]["country"], "Italy")
        self.assertIn("intent", turn_json)  # the raw extraction is still recorded too


class SelectConversationsTests(TestCase):
    def _conversations(self):
        return [
            _conversation(turns=[ConversationTurn(message="a"), ConversationTurn(message="b")]),
        ]

    def test_filters_by_split_and_family_and_id(self):
        conversations = self._conversations()
        self.assertEqual(
            len(
                select_conversations(
                    conversations, split="dev", family=None, scenario_id=None, sample=None
                )
            ),
            1,
        )
        self.assertEqual(
            len(
                select_conversations(
                    conversations, split="holdout", family=None, scenario_id=None, sample=None
                )
            ),
            0,
        )
        self.assertEqual(
            len(
                select_conversations(
                    conversations, split=None, family=None, scenario_id="TEST-CONV", sample=None
                )
            ),
            1,
        )
        self.assertEqual(
            len(
                select_conversations(
                    conversations, split=None, family="correction", scenario_id=None, sample=None
                )
            ),
            0,
        )
