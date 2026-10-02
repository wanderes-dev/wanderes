import json

from django.core.management.base import BaseCommand, CommandError

from ai.provider import AIProviderError, get_ai_provider
from evaluations.relevance_scenarios import format_report, run_relevance


class Command(BaseCommand):
    help = (
        "Run the ten focused conversational-relevance scenarios "
        "(evaluations/relevance_scenarios.py) through the real orchestration with the "
        "real model: about 30 turns, roughly 100 model calls. Nothing is written unless "
        "--output is given."
    )

    def add_arguments(self, parser):
        parser.add_argument("--show-replies", action="store_true", help="Print each reply's start.")
        parser.add_argument("--output", default=None, help="Also write the results as JSON.")

    def handle(self, *args, **options):
        try:
            results = run_relevance(get_ai_provider())
        except AIProviderError as exc:
            raise CommandError(f"The AI provider failed during the run ({exc}).") from exc
        self.stdout.write(format_report(results, show_replies=options["show_replies"]))
        if options["output"]:
            payload = [
                {
                    "scenario": r.scenario,
                    "step": r.index,
                    "message": r.step.message,
                    "route": r.route,
                    "card": r.card,
                    "measures": r.measures,
                    "failures": r.failures,
                    "reply": r.reply,
                }
                for r in results
            ]
            with open(options["output"], "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
