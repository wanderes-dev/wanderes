import json
import tempfile
from pathlib import Path

from django.test import TestCase

from evaluations.cost import CostTracker
from evaluations.persistence import load_run, save_run
from evaluations.runner import ScenarioResult
from evaluations.scenarios import Scenario


def _passing_result(scenario_id, split="dev"):
    scenario = Scenario(id=scenario_id, split=split, category="straightforward", message="x")
    return ScenarioResult(scenario=scenario, mode="deterministic", flow_matched=True, reply="")


def _failing_result(scenario_id, split="dev"):
    from evaluations.invariants import InvariantResult

    scenario = Scenario(id=scenario_id, split=split, category="straightforward", message="x")
    return ScenarioResult(
        scenario=scenario,
        mode="deterministic",
        flow_matched=True,
        reply="",
        invariants=[InvariantResult("some_check", False, "broken")],
    )


class SaveAndLoadRunTests(TestCase):
    def test_save_run_writes_expected_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = save_run(
                label="test",
                mode="deterministic",
                results=[_passing_result("T-1"), _failing_result("T-2")],
                metamorphic=[],
                cost=CostTracker(model_name="stub"),
                runs_dir=Path(tmp),
            )
            self.assertTrue((run_dir / "meta.json").exists())
            self.assertTrue((run_dir / "results.jsonl").exists())
            self.assertTrue((run_dir / "summary.md").exists())

    def test_meta_json_has_correct_pass_fail_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = save_run(
                label="test",
                mode="deterministic",
                results=[_passing_result("T-1"), _failing_result("T-2")],
                metamorphic=[],
                cost=CostTracker(model_name="stub"),
                runs_dir=Path(tmp),
            )
            meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["pass_count"], 1)
            self.assertEqual(meta["fail_count"], 1)
            self.assertEqual(meta["scenario_count"], 2)

    def test_load_run_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = save_run(
                label="test",
                mode="deterministic",
                results=[_passing_result("T-1")],
                metamorphic=[],
                cost=CostTracker(model_name="stub"),
                runs_dir=Path(tmp),
            )
            meta, results = load_run(run_dir)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["id"], "T-1")
            self.assertTrue(results[0]["passed"])

    def test_summary_mentions_failure_taxonomy(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = save_run(
                label="test",
                mode="deterministic",
                results=[_failing_result("T-2")],
                metamorphic=[],
                cost=CostTracker(model_name="stub"),
                runs_dir=Path(tmp),
            )
            summary = (run_dir / "summary.md").read_text(encoding="utf-8")
            self.assertIn("Failure taxonomy", summary)
