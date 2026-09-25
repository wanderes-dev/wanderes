import tempfile
from pathlib import Path

from django.test import TestCase

from evaluations.compare import compare_runs
from evaluations.cost import CostTracker
from evaluations.invariants import InvariantResult
from evaluations.persistence import save_run
from evaluations.runner import ScenarioResult
from evaluations.scenarios import Scenario


def _result(scenario_id, *, passed):
    scenario = Scenario(id=scenario_id, split="dev", category="straightforward", message="x")
    invariants = [] if passed else [InvariantResult("some_check", False, "broken")]
    return ScenarioResult(
        scenario=scenario, mode="deterministic", flow_matched=True, reply="", invariants=invariants
    )


class CompareRunsTests(TestCase):
    def test_detects_newly_fixed_and_newly_broken(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs_dir = Path(tmp)
            baseline = save_run(
                label="baseline",
                mode="deterministic",
                results=[
                    _result("A", passed=False),
                    _result("B", passed=True),
                    _result("C", passed=True),
                ],
                metamorphic=[],
                cost=CostTracker(model_name="stub"),
                runs_dir=runs_dir,
            )
            candidate = save_run(
                label="candidate",
                mode="deterministic",
                results=[
                    _result("A", passed=True),
                    _result("B", passed=False),
                    _result("C", passed=True),
                ],
                metamorphic=[],
                cost=CostTracker(model_name="stub"),
                runs_dir=runs_dir,
            )

            diff = compare_runs(baseline, candidate)

            self.assertEqual(diff.newly_fixed, ("A",))
            self.assertEqual(diff.newly_broken, ("B",))
            self.assertEqual(diff.still_passing_count, 1)

    def test_corpus_changes_are_reported_separately(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs_dir = Path(tmp)
            baseline = save_run(
                label="baseline",
                mode="deterministic",
                results=[_result("A", passed=True)],
                metamorphic=[],
                cost=CostTracker(model_name="stub"),
                runs_dir=runs_dir,
            )
            candidate = save_run(
                label="candidate",
                mode="deterministic",
                results=[_result("A", passed=True), _result("NEW", passed=True)],
                metamorphic=[],
                cost=CostTracker(model_name="stub"),
                runs_dir=runs_dir,
            )

            diff = compare_runs(baseline, candidate)

            self.assertEqual(diff.candidate_only_ids, ("NEW",))
            self.assertEqual(diff.baseline_only_ids, ())

    def test_render_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs_dir = Path(tmp)
            baseline = save_run(
                label="baseline",
                mode="deterministic",
                results=[_result("A", passed=True)],
                metamorphic=[],
                cost=CostTracker(model_name="stub"),
                runs_dir=runs_dir,
            )
            candidate = save_run(
                label="candidate",
                mode="deterministic",
                results=[_result("A", passed=False)],
                metamorphic=[],
                cost=CostTracker(model_name="stub"),
                runs_dir=runs_dir,
            )
            diff = compare_runs(baseline, candidate)
            rendered = diff.render()
            self.assertIn("newly broken", rendered.lower())
