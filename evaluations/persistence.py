"""Persists one evaluation run as a small set of lightweight artifacts -
JSONL for machine-readable results, one Markdown file for a human
summary. Deliberately not a database table: synthetic evaluation runs
never belong in production user analytics tables, and Postgres buys
nothing here that a versioned file doesn't already give for free
(diffable, greppable, trivially copied into a PR description).
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from .cost import CostTracker
from .intent_eval import aggregate_field_accuracy
from .metamorphic import MetamorphicComparison
from .runner import ScenarioResult
from .scenarios import CORPUS_VERSION
from .taxonomy import count_by_category

RUNS_DIR = Path(__file__).resolve().parent / "runs"


def _git_sha() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None


def save_run(
    *,
    label: str,
    mode: str,
    results: list[ScenarioResult],
    metamorphic: list[MetamorphicComparison],
    cost: CostTracker,
    runs_dir: Path | None = None,
) -> Path:
    runs_dir = runs_dir or RUNS_DIR
    timestamp = datetime.now(UTC)
    run_id = f"{timestamp.strftime('%Y%m%d-%H%M%S')}_{label}"
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "run_id": run_id,
        "label": label,
        "mode": mode,
        "corpus_version": CORPUS_VERSION,
        "git_sha": _git_sha(),
        "timestamp": timestamp.isoformat(),
        "scenario_count": len(results),
        "pass_count": sum(r.passed for r in results),
        "fail_count": sum(not r.passed for r in results),
        "cost": cost.to_json(),
        "failure_taxonomy": count_by_category(
            [(name, r.scenario.category) for r in results for name in r.failed_check_names()]
        ),
    }
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    with open(run_dir / "results.jsonl", "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r.to_json()) + "\n")

    with open(run_dir / "metamorphic.jsonl", "w", encoding="utf-8") as f:
        for m in metamorphic:
            f.write(json.dumps(m.to_json()) + "\n")

    (run_dir / "summary.md").write_text(
        render_summary(meta, results, metamorphic), encoding="utf-8"
    )

    return run_dir


def load_run(run_dir: Path) -> tuple[dict, list[dict]]:
    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    results = []
    with open(run_dir / "results.jsonl", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                results.append(json.loads(line))
    return meta, results


def render_summary(
    meta: dict, results: list[ScenarioResult], metamorphic: list[MetamorphicComparison]
) -> str:
    lines = [
        "# Wanderes Recommendation Evaluation",
        "",
        f"- Run: `{meta['run_id']}` ({meta['mode']} mode)",
        f"- Corpus version: `{meta['corpus_version']}`",
        f"- Git commit: `{meta['git_sha']}`",
        f"- Scenarios: {meta['scenario_count']} "
        f"({meta['pass_count']} passed, {meta['fail_count']} failed)",
        f"- Estimated cost: ${meta['cost']['estimated_usd']} "
        f"({meta['cost']['pipeline_scenarios']} pipeline calls, "
        f"{meta['cost']['judge_calls']} judge calls)",
        "",
        "## Failure taxonomy",
        "",
    ]
    if meta["failure_taxonomy"]:
        for category, count in sorted(meta["failure_taxonomy"].items(), key=lambda kv: -kv[1]):
            lines.append(f"- {category}: {count}")
    else:
        lines.append("(no failures)")
    lines.append("")

    by_split: dict[str, list[ScenarioResult]] = {}
    for r in results:
        by_split.setdefault(r.scenario.split, []).append(r)
    for split, split_results in sorted(by_split.items()):
        passed = sum(r.passed for r in split_results)
        lines.append(f"## {split.title()} split: {passed}/{len(split_results)} passed")
        lines.append("")

    intent_results = [r.intent_eval for r in results if r.intent_eval is not None]
    if intent_results:
        lines.append("## Intent extraction accuracy (by field)")
        lines.append("")
        for field_name, accuracy in sorted(aggregate_field_accuracy(intent_results).items()):
            lines.append(f"- `{field_name}`: {accuracy:.0%}")
        lines.append("")

    failed = [r for r in results if not r.passed]
    if failed:
        lines.append("## Failed scenarios")
        lines.append("")
        for r in failed[:50]:
            checks = ", ".join(r.failed_check_names())
            lines.append(f"- `{r.scenario.id}` ({r.scenario.category}): {checks}")
        if len(failed) > 50:
            lines.append(f"- ... and {len(failed) - 50} more (see results.jsonl)")
        lines.append("")

    if metamorphic:
        failed_pairs = [m for m in metamorphic if any(not c.passed for c in m.checks)]
        lines.append("## Metamorphic pairs")
        lines.append("")
        lines.append(
            f"{len(metamorphic)} pairs run, {len(failed_pairs)} with a failed structural check."
        )
        for m in failed_pairs:
            details = [c.detail for c in m.checks if not c.passed]
            lines.append(f"- `{m.pair_id}` ({m.axis}): {details}")
        lines.append("")

    return "\n".join(lines)
