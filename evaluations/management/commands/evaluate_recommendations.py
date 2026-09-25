from django.core.management.base import BaseCommand, CommandError

from evaluations.metamorphic import run_metamorphic_pair
from evaluations.persistence import save_run
from evaluations.requests import build_request
from evaluations.runner import run_scenarios, select_scenarios
from evaluations.scenarios import load_corpus, metamorphic_pairs
from evaluations.trace import trace_recommendations
from integrations.climate import get_climate_provider


class Command(BaseCommand):
    help = (
        "Run the synthetic recommendation-quality evaluation corpus "
        "(evaluations/corpus/scenarios.jsonl). Deterministic-only by "
        "default - zero AI calls, zero cost, exercises only "
        "recommendations.scoring. Pass --sample/--full to also run the "
        "real AI pipeline (intent extraction + explanation), which "
        "costs real OpenAI calls - see evaluations.cost for a rough "
        "per-run estimate. Never runs as part of the normal `pytest` "
        "suite; this is its own opt-in command."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--split",
            choices=["dev", "holdout", "all"],
            default="dev",
            help="Which scenario split to run (default: dev - never tune against holdout).",
        )
        parser.add_argument(
            "--sample",
            type=int,
            default=None,
            help="Run the real AI pipeline against a random sample of N scenarios.",
        )
        parser.add_argument(
            "--full",
            action="store_true",
            help="Run the real AI pipeline against every selected scenario (real AI cost).",
        )
        parser.add_argument(
            "--deterministic-only",
            action="store_true",
            help="Force deterministic-only mode even if --sample/--full is also given.",
        )
        parser.add_argument(
            "--with-llm-judge",
            action="store_true",
            help=(
                "Also run the optional LLM-as-judge pass for subjective explanation "
                "quality (real AI cost; only meaningful together with --sample/--full)."
            ),
        )
        parser.add_argument(
            "--label",
            default="run",
            help="Short label folded into this run's artifact directory name.",
        )
        parser.add_argument(
            "--seed", type=int, default=1337, help="Sampling seed, for reproducibility."
        )
        parser.add_argument(
            "--trace",
            metavar="SCENARIO_ID",
            default=None,
            help="Print the full recommendation trace for one scenario id (dev diagnostics) "
            "and exit.",
        )

    def handle(self, *args, **options):
        scenarios = load_corpus()

        if options["trace"]:
            self._print_trace(scenarios, options["trace"])
            return

        split = None if options["split"] == "all" else options["split"]
        deterministic_only = options["deterministic_only"] or not (
            options["full"] or options["sample"]
        )
        sample = None if (deterministic_only or options["full"]) else options["sample"]
        selected = select_scenarios(scenarios, split=split, sample=sample, seed=options["seed"])

        mode_label = "deterministic-only" if deterministic_only else "full pipeline"
        judge_label = ", +LLM judge" if options["with_llm_judge"] and not deterministic_only else ""
        self.stdout.write(f"Running {len(selected)} scenario(s) ({mode_label}{judge_label})...")

        results, cost = run_scenarios(
            selected,
            deterministic_only=deterministic_only,
            with_llm_judge=options["with_llm_judge"],
        )

        metamorphic_results = []
        climate_provider = get_climate_provider()
        for scenario_a, scenario_b in metamorphic_pairs(scenarios):
            if split is not None and split not in (scenario_a.split, scenario_b.split):
                continue
            metamorphic_results.append(
                run_metamorphic_pair(scenario_a, scenario_b, climate_provider=climate_provider)
            )

        run_dir = save_run(
            label=options["label"],
            mode="deterministic" if deterministic_only else "full",
            results=results,
            metamorphic=metamorphic_results,
            cost=cost,
        )

        passed = sum(r.passed for r in results)
        style = self.style.SUCCESS if passed == len(results) else self.style.WARNING
        self.stdout.write(style(f"{passed}/{len(results)} scenarios passed."))
        if not deterministic_only:
            self.stdout.write(f"Estimated cost: ${cost.estimated_usd:.4f}")
        self.stdout.write(f"Artifacts written to {run_dir}")

    def _print_trace(self, scenarios, scenario_id):
        scenario = next((s for s in scenarios if s.id == scenario_id), None)
        if scenario is None:
            raise CommandError(f"No scenario with id {scenario_id!r}")
        if scenario.deterministic_request is None:
            raise CommandError(f"Scenario {scenario_id!r} has no deterministic_request to trace.")
        request = build_request(scenario.deterministic_request)
        _, trace = trace_recommendations(request, climate_provider=get_climate_provider())
        self.stdout.write(f"Scenario {scenario_id}: {scenario.message!r}\n")
        self.stdout.write(trace.render())
