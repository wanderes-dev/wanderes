from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from evaluations.compare import compare_runs
from evaluations.persistence import RUNS_DIR


class Command(BaseCommand):
    help = (
        "Compare two evaluation run artifacts produced by "
        "evaluate_recommendations - newly fixed scenarios, newly broken "
        "scenarios, unchanged failures, pass-rate deltas."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "baseline", help="Baseline run directory name (under evaluations/runs/) or full path."
        )
        parser.add_argument(
            "candidate", help="Candidate run directory name (under evaluations/runs/) or full path."
        )

    def handle(self, *args, **options):
        baseline_dir = self._resolve(options["baseline"])
        candidate_dir = self._resolve(options["candidate"])
        diff = compare_runs(baseline_dir, candidate_dir)
        self.stdout.write(diff.render())

    @staticmethod
    def _resolve(value: str) -> Path:
        path = Path(value)
        if path.exists():
            return path
        candidate = RUNS_DIR / value
        if candidate.exists():
            return candidate
        raise CommandError(f"No run found at {value!r} or {candidate}")
