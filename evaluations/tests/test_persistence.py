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


def _infrastructure_failure_result(scenario_id, split="dev"):
    scenario = Scenario(id=scenario_id, split=split, category="straightforward", message="x")
    return ScenarioResult(
        scenario=scenario,
        mode="deterministic",
        flow_matched=True,
        reply="",
        is_infrastructure_failure=True,
        infrastructure_failure_reason="missing weather fixture",
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

    def test_infrastructure_failures_excluded_from_quality_denominator(self):
        # §11/§8: a scenario that never got evaluated because of a
        # missing weather fixture must not silently count against - or
        # for - recommendation quality. scenario_count stays the raw,
        # unfiltered total; evaluable_count/quality_pass_count exclude
        # infrastructure failures entirely.
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = save_run(
                label="test",
                mode="deterministic",
                results=[
                    _passing_result("T-1"),
                    _failing_result("T-2"),
                    _infrastructure_failure_result("T-3"),
                ],
                metamorphic=[],
                cost=CostTracker(model_name="stub"),
                runs_dir=Path(tmp),
            )
            meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["scenario_count"], 3)
            self.assertEqual(meta["evaluable_count"], 2)
            self.assertEqual(meta["infrastructure_failure_count"], 1)
            self.assertEqual(meta["quality_pass_count"], 1)
            self.assertAlmostEqual(meta["quality_pass_rate"], 0.5)

    def test_quality_pass_rate_is_none_when_nothing_is_evaluable(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = save_run(
                label="test",
                mode="deterministic",
                results=[_infrastructure_failure_result("T-1")],
                metamorphic=[],
                cost=CostTracker(model_name="stub"),
                runs_dir=Path(tmp),
            )
            meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
            self.assertIsNone(meta["quality_pass_rate"])

    def test_infrastructure_failure_reported_as_dependency_failure_in_taxonomy(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = save_run(
                label="test",
                mode="deterministic",
                results=[_infrastructure_failure_result("T-1")],
                metamorphic=[],
                cost=CostTracker(model_name="stub"),
                runs_dir=Path(tmp),
            )
            meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["failure_taxonomy"], {"DEPENDENCY_FAILURE": 1})

    def test_summary_separates_infrastructure_from_quality_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = save_run(
                label="test",
                mode="deterministic",
                results=[_failing_result("T-2"), _infrastructure_failure_result("T-3")],
                metamorphic=[],
                cost=CostTracker(model_name="stub"),
                runs_dir=Path(tmp),
            )
            summary = (run_dir / "summary.md").read_text(encoding="utf-8")
            self.assertIn("Infrastructure failures (excluded from quality result above)", summary)
            self.assertIn("Failed scenarios (quality)", summary)
            self.assertIn("T-3", summary)
            self.assertIn("T-2", summary)
