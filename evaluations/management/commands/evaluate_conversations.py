from django.core.management.base import BaseCommand, CommandError

from ai.provider import get_ai_provider
from evaluations.conversation_persistence import save_conversation_run
from evaluations.conversation_runner import run_conversation, select_conversations
from evaluations.conversation_scenarios import load_conversation_corpus
from evaluations.cost import CostTracker
from evaluations.weather_fixtures import FixtureWeatherProvider


class Command(BaseCommand):
    help = (
        "Run the multi-turn conversation evaluation corpus "
        "(evaluations/corpus/conversations.jsonl) against the real "
        "production orchestration path - a second, independent evaluation "
        "dimension alongside evaluate_recommendations's single-request "
        "corpus (never modified by this command). Every conversation "
        "makes real AI calls per turn - there is no zero-cost "
        "deterministic-only mode here, since intent has to be freshly "
        "extracted from a real model at every turn for a state-persistence "
        "question to mean anything. Use --dry-run to estimate cost first."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--split",
            choices=["dev", "holdout", "all"],
            default="dev",
            help="Which split to run (default: dev - never tune against holdout).",
        )
        parser.add_argument("--family", default=None, help="Only run one scenario family.")
        parser.add_argument("--scenario", default=None, help="Only run one conversation id.")
        parser.add_argument("--sample", type=int, default=None, help="Run a random sample of N.")
        parser.add_argument(
            "--full", action="store_true", help="Run every selected conversation (real AI cost)."
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Estimate LLM calls/cost for the selection and exit - no AI calls made.",
        )
        parser.add_argument(
            "--label", default="run", help="Label folded into the run directory name."
        )
        parser.add_argument("--seed", type=int, default=1337, help="Sampling seed.")
        parser.add_argument(
            "--trace",
            metavar="CONVERSATION_ID",
            default=None,
            help="Run one conversation and print its full turn-by-turn trace (dev diagnostics).",
        )

    def handle(self, *args, **options):
        conversations = load_conversation_corpus()
        split = None if options["split"] == "all" else options["split"]

        if options["trace"]:
            self._print_trace(conversations, options["trace"])
            return

        sample = None if options["full"] else options["sample"]
        selected = select_conversations(
            conversations,
            split=split,
            family=options["family"],
            scenario_id=options["scenario"],
            sample=sample,
            seed=options["seed"],
        )
        if not selected:
            raise CommandError("No conversations matched the given selection.")

        total_turns = sum(len(c.turns) for c in selected)
        if options["dry_run"]:
            estimate = CostTracker(model_name="estimate")
            for c in selected:
                for turn in c.turns:
                    estimate.record_pipeline_call(scenario_message=turn.message, reply="")
            self.stdout.write(
                f"{len(selected)} conversation(s), {total_turns} turn(s) -> "
                f"~{total_turns} real AI calls (up to 3x that many requests).\n"
                f"Estimated cost: ${estimate.estimated_usd:.4f}"
            )
            return

        self.stdout.write(f"Running {len(selected)} conversation(s), {total_turns} turn(s)...")
        ai_provider = get_ai_provider()
        climate_provider = FixtureWeatherProvider()
        cost = CostTracker(model_name=self._model_name())
        results = [
            run_conversation(
                c, ai_provider=ai_provider, climate_provider=climate_provider, cost=cost
            )
            for c in selected
        ]

        run_dir = save_conversation_run(label=options["label"], results=results, cost=cost)

        evaluable = [r for r in results if r.evaluable]
        infra = len(results) - len(evaluable)
        passed = sum(r.passed for r in evaluable)
        self.stdout.write(f"{len(results)} conversation(s) total, {len(evaluable)} evaluable.")
        if infra:
            self.stdout.write(
                self.style.WARNING(
                    f"{infra} infrastructure failure(s) (missing weather fixture) - "
                    "excluded from the quality result below."
                )
            )
        style = self.style.SUCCESS if passed == len(evaluable) else self.style.WARNING
        self.stdout.write(style(f"{passed}/{len(evaluable)} evaluable conversations passed."))
        self.stdout.write(f"Estimated cost: ${cost.estimated_usd:.4f}")
        self.stdout.write(f"Artifacts written to {run_dir}")

    def _model_name(self) -> str:
        from django.conf import settings

        return getattr(settings, "AI_MODEL", "unknown")

    def _print_trace(self, conversations, conversation_id):
        scenario = next((c for c in conversations if c.id == conversation_id), None)
        if scenario is None:
            raise CommandError(f"No conversation with id {conversation_id!r}")
        ai_provider = get_ai_provider()
        climate_provider = FixtureWeatherProvider()
        cost = CostTracker(model_name=self._model_name())
        result = run_conversation(
            scenario, ai_provider=ai_provider, climate_provider=climate_provider, cost=cost
        )
        self.stdout.write(result.render_trace())
