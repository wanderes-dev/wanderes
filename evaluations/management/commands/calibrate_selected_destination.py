import json

from django.core.management.base import BaseCommand, CommandError

from ai.provider import AIProviderError, get_ai_provider
from evaluations.selected_destination_calibration import (
    format_probes,
    format_report,
    run_calibration,
    run_probes,
)


class Command(BaseCommand):
    help = (
        "Measure ai.orchestration's selected_destination_name against the frozen "
        "calibration set (evaluations/selected_destination_calibration.py): one real "
        "structured call per case through the production prompt and schema (about 100 "
        "calls); nothing is written unless --output is given. With --probes, run the "
        "full-pipeline conversations instead."
    )

    def add_arguments(self, parser):
        parser.add_argument("--output", default=None, help="Also write the raw results as JSON.")
        parser.add_argument(
            "--probes",
            action="store_true",
            help="Instead of the extraction measurement, run the full-pipeline probes "
            "(real orchestration, one fresh conversation per probe).",
        )

    def handle(self, *args, **options):
        provider = get_ai_provider()
        if options["probes"]:
            try:
                self.stdout.write(format_probes(run_probes(provider)))
            except AIProviderError as exc:
                raise CommandError(f"The AI provider failed during the probes ({exc}).") from exc
            return

        try:
            report = run_calibration(provider)
        except AIProviderError as exc:
            raise CommandError(
                f"The AI provider failed during the calibration ({exc}); "
                "a partial measurement is not reported."
            ) from exc
        self.stdout.write(format_report(report))

        if options["output"]:
            payload = [
                {
                    "id": r.case.id,
                    "category": r.case.category,
                    "message": r.case.message,
                    "raw_type": r.raw_type,
                    "raw_name": r.raw_name,
                    "final_name": r.final_name,
                    "passed": r.passed,
                    "reason": r.reason,
                }
                for r in report.results
            ]
            with open(options["output"], "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
