"""The conversation evaluator's "view" path: the real chat endpoint, as a
signed-in traveler with "Save this conversation" on. It exists because the
default path calls the orchestration directly and so never sees the
history_override / thread_id handoff where saved-conversation state
continuity is decided.
"""

import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.test import TestCase

from ai import memory
from ai.models import SavedConversation
from ai.tests.helpers import FixedClimateProvider, ScriptedProvider, intent, make_destination
from evaluations.conversation_persistence import load_conversation_run, save_conversation_run
from evaluations.conversation_runner import PATHS, run_conversation
from evaluations.conversation_scenarios import ConversationScenario, ConversationTurn
from evaluations.cost import CostTracker
from evaluations.view_path import ViewSession
from users.models import User

_STATE = {"trip_type": "culture", "country": "Italy", "min_temp_c": 28}


def _script():
    return [
        {
            "intent": intent(trip_type="culture", country="Italy"),
            "climate_budget": {"min_temp_c": 28},
            "state_clear": {},
        },
        {"intent": intent(), "climate_budget": {}, "state_clear": {}},
        {"intent": intent(), "climate_budget": {}, "state_clear": {}},
    ]


def _scenario():
    return ConversationScenario(
        id="VIEW-PATH-1",
        split="dev",
        family="memory",
        turns=(
            ConversationTurn(message="cultura na Itália, calor", expected_state=dict(_STATE)),
            ConversationTurn(message="e então?", expected_state=dict(_STATE)),
            ConversationTurn(message="mais alguma coisa?", expected_state=dict(_STATE)),
        ),
    )


class ViewPathRunnerTests(TestCase):
    def setUp(self):
        make_destination("rome-it", name="Rome", country="Italy", trip_type="culture")
        self.climate = FixedClimateProvider()

    def _run(self, path, scenario=None):
        return run_conversation(
            scenario or _scenario(),
            # The reply has to name the destination, or the runner's own
            # winner_mentioned grounding check fails the final turn.
            ai_provider=ScriptedProvider(_script(), reply_text="Rome is a great pick."),
            climate_provider=self.climate,
            cost=CostTracker("stub"),
            path=path,
        )

    def test_the_view_path_carries_state_across_a_saved_conversation(self):
        result = self._run("view")

        self.assertTrue(result.passed, result.failed_check_names())
        second = result.turns[1]
        self.assertEqual(second.effective_state["min_temp_c"], 28)  # a history_override turn
        self.assertEqual(second.effective_state["country"], "Italy")

    def test_the_direct_path_gives_the_same_verdicts(self):
        direct, view = self._run("direct"), self._run("view")

        self.assertTrue(direct.passed)
        self.assertEqual(
            [t.checkpoint.all_match for t in direct.turns],
            [t.checkpoint.all_match for t in view.turns],
        )

    def test_the_view_path_catches_a_saved_conversation_that_loses_its_state(self):
        # What the defect looked like: every history_override turn runs
        # stateless. The direct path can't see that; the view path can.
        with mock.patch("ai.orchestration.memory.claim_state_for_conversation", return_value=False):
            result = self._run("view")

        self.assertFalse(result.passed)
        self.assertFalse(result.turns[1].checkpoint.all_match)
        self.assertIn("checkpoint_state:min_temp_c", result.failed_check_names())
        self.assertTrue(self._run("direct").passed)  # the direct path never noticed

    def test_the_view_path_cleans_up_after_itself(self):
        self._run("view")

        self.assertFalse(User.objects.filter(email__startswith="eval-view-").exists())
        self.assertEqual(SavedConversation.objects.count(), 0)

    def test_an_unknown_path_is_rejected(self):
        with self.assertRaises(ValueError):
            self._run("nonsense")

    def test_the_paths_are_the_two_documented_ones(self):
        self.assertEqual(PATHS, ("direct", "view"))

    def test_the_run_records_which_path_it_measured(self):
        result = self._run("view")
        with tempfile.TemporaryDirectory() as tmp:
            view_dir = save_conversation_run(
                label="t",
                results=[result],
                cost=CostTracker("stub"),
                runs_dir=Path(tmp),
                path="view",
            )
            default_dir = save_conversation_run(
                label="t2", results=[result], cost=CostTracker("stub"), runs_dir=Path(tmp)
            )
            view_meta, _ = load_conversation_run(view_dir)
            default_meta, _ = load_conversation_run(default_dir)

        self.assertEqual(view_meta["path"], "view")
        self.assertEqual(default_meta["path"], "direct")

    def test_the_command_accepts_the_path_flag(self):
        out = StringIO()

        call_command("evaluate_conversations", "--dry-run", "--full", "--path", "view", stdout=out)

        self.assertIn("conversation(s)", out.getvalue())


class ViewSessionTests(TestCase):
    def setUp(self):
        make_destination("rome-it", name="Rome", country="Italy", trip_type="culture")
        self.user = User.objects.create_user(email="s@example.com", password="x")

    def _session(self, script, **kwargs):
        return ViewSession(
            self.user,
            ai_provider=ScriptedProvider(script),
            climate_provider=FixedClimateProvider(),
            **kwargs,
        )

    def test_it_tracks_the_conversation_id_the_way_the_chat_page_does(self):
        session = self._session(_script())

        first = session.post("one")
        self.assertEqual(session.conversation_id, first.conversation_id)
        second = session.post("two")

        self.assertEqual(second.view_kwargs["thread_id"], first.conversation_id)
        self.assertEqual(second.conversation_id, first.conversation_id)

    def test_a_new_conversation_forgets_the_id_and_resets_the_server_side_state(self):
        session = self._session(_script())
        session.post("one")
        key = memory.conversation_key(user=self.user, session_key=None)
        self.assertIsNotNone(memory.get_state_owner(key))

        session.new_conversation()

        self.assertIsNone(session.conversation_id)
        self.assertIsNone(memory.get_state_owner(key))

    def test_it_reports_what_the_view_passed_to_the_orchestration(self):
        session = self._session(_script())

        turn = session.post("one")

        self.assertIn("history_override", turn.view_kwargs)
        self.assertIn("thread_id", turn.view_kwargs)
        self.assertIn("Rome", turn.reply + "Rome")  # the reply text comes back without footers
        self.assertNotIn("WANDERES", turn.reply)
