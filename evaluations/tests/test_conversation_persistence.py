import tempfile
from pathlib import Path

from django.test import TestCase

from evaluations.conversation_persistence import load_conversation_run, save_conversation_run
from evaluations.conversation_runner import run_conversation
from evaluations.conversation_scenarios import ConversationScenario, ConversationTurn
from evaluations.cost import CostTracker
from integrations.climate.base import MonthlyClimateSummary
from travel.models import Destination

from .test_conversation_runner import _BASE_INTENT, _StubProvider


class _AlwaysSucceedsClimateProvider:
    def get_monthly_climate(self, *, latitude, longitude, month, year=None):
        return MonthlyClimateSummary(2025, month, 28.0, 20.0, 5.0)

    def __bool__(self):
        return True


class SaveConversationRunTests(TestCase):
    def setUp(self):
        Destination.objects.create(
            slug="beach-1",
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

    def test_writes_expected_artifacts_and_metrics(self):
        provider = _StubProvider(dict(_BASE_INTENT))
        conversation = ConversationScenario(
            id="PERSIST-1",
            split="dev",
            family="drift",
            turns=(
                ConversationTurn(message="quero praia", expected_state={"trip_type": "beach"}),
                ConversationTurn(message="algo mais?", expected_state={"trip_type": "beach"}),
            ),
        )
        cost = CostTracker("stub")
        result = run_conversation(
            conversation,
            ai_provider=provider,
            climate_provider=_AlwaysSucceedsClimateProvider(),
            cost=cost,
        )

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = save_conversation_run(
                label="unit_test", results=[result], cost=cost, runs_dir=Path(tmp)
            )
            self.assertTrue((run_dir / "meta.json").exists())
            self.assertTrue((run_dir / "results.jsonl").exists())
            self.assertTrue((run_dir / "summary.md").exists())

            meta, results_json = load_conversation_run(run_dir)
            self.assertEqual(meta["conversation_count"], 1)
            self.assertEqual(meta["evaluable_count"], 1)
            self.assertEqual(meta["quality_pass_count"], 1)
            self.assertEqual(meta["checkpoint_total"], 2)
            self.assertEqual(meta["checkpoint_passed"], 2)
            self.assertIn("retained_field_accuracy", meta["metrics"])
            self.assertEqual(len(results_json), 1)

    def test_infrastructure_failure_excluded_from_quality_denominator(self):
        from evaluations.weather_fixtures import MissingWeatherFixtureError

        class _AlwaysMissing:
            def get_monthly_climate(self, **kwargs):
                raise MissingWeatherFixtureError(1.0, 1.0, 1)

            def __bool__(self):
                return True

        provider = _StubProvider({**_BASE_INTENT, "trip_type": "beach"})
        conversation = ConversationScenario(
            id="PERSIST-2",
            split="dev",
            family="drift",
            turns=(
                ConversationTurn(message="a", expected_state={"trip_type": "beach"}),
                ConversationTurn(message="b"),
            ),
        )
        cost = CostTracker("stub")
        result = run_conversation(
            conversation, ai_provider=provider, climate_provider=_AlwaysMissing(), cost=cost
        )
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = save_conversation_run(
                label="unit_test", results=[result], cost=cost, runs_dir=Path(tmp)
            )
            meta, _ = load_conversation_run(run_dir)
            self.assertEqual(meta["conversation_count"], 1)
            self.assertEqual(meta["evaluable_count"], 0)
            self.assertEqual(meta["infrastructure_failure_count"], 1)
            self.assertIsNone(meta["quality_pass_rate"])
