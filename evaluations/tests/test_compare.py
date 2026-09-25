import json
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


def _infrastructure_failure(scenario_id):
    scenario = Scenario(id=scenario_id, split="dev", category="straightforward", message="x")
    return ScenarioResult(
        scenario=scenario,
        mode="deterministic",
        flow_matched=True,
        reply="",
        is_infrastructure_failure=True,
        infrastructure_failure_reason="missing weather fixture",
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

    def test_infrastructure_failure_excluded_from_fixed_and_broken(self):
        # Cycle 1.5 §12/§13: a scenario that was an infrastructure
        # failure in either run must never be counted as newly_fixed or
        # newly_broken - we genuinely don't know if it would have passed,
        # so guessing either way would misreport a real regression/fix.
        with tempfile.TemporaryDirectory() as tmp:
            runs_dir = Path(tmp)
            baseline = save_run(
                label="baseline",
                mode="deterministic",
                results=[
                    _result("A", passed=False),
                    _infrastructure_failure("B"),
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
                    _result("B", passed=True),
                    _result("C", passed=True),
                ],
                metamorphic=[],
                cost=CostTracker(model_name="stub"),
                runs_dir=runs_dir,
            )

            diff = compare_runs(baseline, candidate)

            self.assertEqual(diff.newly_fixed, ("A",))
            self.assertEqual(diff.infrastructure_affected, ("B",))
            self.assertNotIn("B", diff.newly_fixed)
            self.assertNotIn("B", diff.newly_broken)

    def test_infrastructure_affected_is_reported_when_only_candidate_side_fails(self):
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
                results=[_infrastructure_failure("A")],
                metamorphic=[],
                cost=CostTracker(model_name="stub"),
                runs_dir=runs_dir,
            )

            diff = compare_runs(baseline, candidate)

            self.assertEqual(diff.infrastructure_affected, ("A",))
            self.assertEqual(diff.newly_broken, ())
            self.assertEqual(diff.still_failing, ())

    def test_old_runs_without_the_field_are_treated_as_not_infrastructure_affected(self):
        # Backward compatibility with evaluations/runs/20260925-114531_baseline/
        # and evaluations/runs/20260925-142147_cycle1/, which predate
        # is_infrastructure_failure entirely and must never be rewritten.
        with tempfile.TemporaryDirectory() as tmp:
            runs_dir = Path(tmp)
            baseline_dir = save_run(
                label="baseline",
                mode="deterministic",
                results=[_result("A", passed=False)],
                metamorphic=[],
                cost=CostTracker(model_name="stub"),
                runs_dir=runs_dir,
            )
            candidate_dir = save_run(
                label="candidate",
                mode="deterministic",
                results=[_result("A", passed=True)],
                metamorphic=[],
                cost=CostTracker(model_name="stub"),
                runs_dir=runs_dir,
            )
            # Simulate a pre-Cycle-1.5 artifact by stripping the field
            # from the saved JSONL, exactly as the real historical runs
            # look on disk today.
            results_path = baseline_dir / "results.jsonl"
            row = json.loads(results_path.read_text(encoding="utf-8"))
            del row["is_infrastructure_failure"]
            results_path.write_text(json.dumps(row) + "\n", encoding="utf-8")

            diff = compare_runs(baseline_dir, candidate_dir)

            self.assertEqual(diff.newly_fixed, ("A",))
            self.assertEqual(diff.infrastructure_affected, ())

    def test_render_includes_infrastructure_affected_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs_dir = Path(tmp)
            baseline = save_run(
                label="baseline",
                mode="deterministic",
                results=[_infrastructure_failure("A")],
                metamorphic=[],
                cost=CostTracker(model_name="stub"),
                runs_dir=runs_dir,
            )
            candidate = save_run(
                label="candidate",
                mode="deterministic",
                results=[_infrastructure_failure("A")],
                metamorphic=[],
                cost=CostTracker(model_name="stub"),
                runs_dir=runs_dir,
            )
            diff = compare_runs(baseline, candidate)
            rendered = diff.render()
            self.assertIn("Infrastructure-affected", rendered)
            self.assertIn("A", rendered)
