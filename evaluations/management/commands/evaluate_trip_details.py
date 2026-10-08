import json

from django.core.management.base import BaseCommand, CommandError

from ai.provider import AIProviderError, get_ai_provider
from evaluations.trip_details_set import format_report, run_trip_details_set


class Command(BaseCommand):
    help = (
        "Run the frozen set of trip-details phrases (evaluations/trip_details_set.py) through "
        "the real extraction call with the real model: 39 calls. Nothing is written unless "
        "--output is given."
    )

    def add_arguments(self, parser):
        parser.add_argument("--output", default=None, help="Also write the results as JSON.")

    def handle(self, *args, **options):
        try:
            results = run_trip_details_set(get_ai_provider())
        except AIProviderError as exc:
            raise CommandError(f"The AI provider failed during the run ({exc}).") from exc
        self.stdout.write(format_report(results))
        if options["output"]:
            payload = [
                {
                    "id": r.phrase.id,
                    "message": r.phrase.message,
                    "parsed": r.parsed,
                    "differences": r.differences,
                }
                for r in results
            ]
            with open(options["output"], "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
