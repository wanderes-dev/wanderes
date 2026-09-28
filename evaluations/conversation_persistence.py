"""Persists a conversation-evaluation run - same file-based, immutable-once-
committed convention as evaluations.persistence (§13 of the single-request
framework doc), under the same evaluations/runs/ directory so both
evaluation dimensions share one place to look, never a second parallel
"runs" tree.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from .conversation_invariants import classify_checkpoint_mismatch
from .conversation_runner import ConversationResult
from .conversation_scenarios import CONVERSATION_CORPUS_VERSION
from .cost import CostTracker
from .persistence import RUNS_DIR, _git_sha
from .taxonomy import FailureCategory, classify_failure


def _checkpoint_taxonomy_category(result: ConversationResult, check_name: str) -> str:
    """checkpoint_state:<field> needs the conversation's own turn history
    to classify (stale vs. lost vs. a plain miss) - evaluations.taxonomy's
    static name table can't do this alone, so this resolves it here and
    falls back to that shared table for every other check name (grounding,
    ranking-independence, reference/exclusion checks already covered by
    the standard entries added there)."""
    if check_name == "no_stale_state_resurrection":
        return FailureCategory.STALE_STATE.value
    if check_name == "no_lost_context":
        return FailureCategory.LOST_CONTEXT.value
    if check_name.startswith("checkpoint_state:"):
        field_name = check_name.split(":", 1)[1]
        for turn in result.checkpoints:
            match = next((c for c in turn.checkpoint.comparisons if c.field == field_name), None)
            if match is None or match.matches:
                continue
            label = classify_checkpoint_mismatch(
                result.scenario,
                field_name=field_name,
                turn_index=turn.turn_index,
                actual_value=match.actual,
            )
            if label == "stale_state":
                return FailureCategory.STALE_STATE.value
            if label == "lost_context":
                return FailureCategory.LOST_CONTEXT.value
        family_default = {
            "correction": FailureCategory.CORRECTION_FAILURE,
            "contradiction": FailureCategory.CONTRADICTION_RESOLUTION,
        }.get(result.scenario.family, FailureCategory.INTENT_EXTRACTION)
        return family_default.value
    return classify_failure(check_name=check_name, scenario_category=result.scenario.family).value


def _family_metric(results: list[ConversationResult], *, family: str) -> tuple[int, int]:
    """(checkpoints_passed, checkpoints_total) across every checkpoint in
    conversations belonging to one family - the per-family accuracy
    metrics (correction/contradiction/irrelevant-info) are all shaped this
    way."""
    passed = total = 0
    for r in results:
        if r.scenario.family != family or not r.evaluable:
            continue
        for t in r.checkpoints:
            total += 1
            passed += int(t.checkpoint.all_match)
    return passed, total


def _retained_field_metric(results: list[ConversationResult]) -> tuple[int, int]:
    """Across every checkpoint in every evaluable conversation, how often
    a field asserted as non-null (still actively true) actually matched -
    the read on "does Wanderes keep believing what it should still
    believe," independent of family."""
    passed = total = 0
    for r in results:
        if not r.evaluable:
            continue
        for t in r.checkpoints:
            for c in t.checkpoint.comparisons:
                if c.expected is None:
                    continue
                total += 1
                passed += int(c.matches)
    return passed, total


def _supersession_metric(results: list[ConversationResult]) -> tuple[int, int]:
    """Across every checkpoint whose authored expected_transitions marks a
    field "superseded" or "removed" at that turn, how often the checkpoint
    correctly showed the new (non-lingering) value."""
    passed = total = 0
    for r in results:
        if not r.evaluable:
            continue
        for turn_index, turn in enumerate(r.scenario.turns):
            if not turn.expected_transitions:
                continue
            superseded_fields = {
                f
                for f, label in turn.expected_transitions.items()
                if label in ("superseded", "removed")
            }
            if not superseded_fields:
                continue
            turn_result = next((t for t in r.turns if t.turn_index == turn_index), None)
            if turn_result is None or turn_result.checkpoint is None:
                continue
            for c in turn_result.checkpoint.comparisons:
                if c.field not in superseded_fields:
                    continue
                total += 1
                passed += int(c.matches)
    return passed, total


def _reference_resolution_metric(results: list[ConversationResult]) -> tuple[int, int]:
    passed = total = 0
    for r in results:
        if not r.evaluable:
            continue
        for t in r.turns:
            if t.reference_resolved is None:
                continue  # corpus-side unresolvable (referenced turn had fewer options), not scored
            total += 1
            passed += int(t.reference_resolved)
    return passed, total


def _exclusion_persistence_metric(results: list[ConversationResult]) -> tuple[int, int]:
    """Denominator is every (conversation, slug-still-expected-excluded)
    assertion across all evaluable conversations with at least one
    exclusion checkpoint; numerator excludes this conversation's own
    violations."""
    passed = total = 0
    for r in results:
        if not r.evaluable:
            continue
        excluded_slugs_seen: set[str] = set()
        for t in r.checkpoints:
            comparison = next(
                (c for c in t.checkpoint.comparisons if c.field == "excluded_slugs"), None
            )
            if comparison is None:
                continue
            excluded_slugs_seen |= set(comparison.expected or [])
        if not excluded_slugs_seen:
            continue
        violated_slugs = {slug for _, slug in r.exclusion_violations}
        total += len(excluded_slugs_seen)
        passed += len(excluded_slugs_seen - violated_slugs)
    return passed, total


def _language_continuity_results(results: list[ConversationResult]) -> dict:
    multilingual = [r for r in results if len({t.language for t in r.scenario.turns}) > 1]
    evaluable = [r for r in multilingual if r.evaluable]
    passed = sum(1 for r in evaluable if r.passed)
    return {
        "conversations": len(multilingual),
        "evaluable": len(evaluable),
        "passed": passed,
    }


def _safe_rate(passed: int, total: int) -> float | None:
    return (passed / total) if total else None


def save_conversation_run(
    *,
    label: str,
    results: list[ConversationResult],
    cost: CostTracker,
    runs_dir: Path | None = None,
) -> Path:
    runs_dir = runs_dir or RUNS_DIR
    timestamp = datetime.now(UTC)
    run_id = f"{timestamp.strftime('%Y%m%d-%H%M%S')}_{label}"
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    evaluable = [r for r in results if r.evaluable]
    infrastructure_failures = [r for r in results if r.is_infrastructure_failure]
    checkpoint_total = sum(r.checkpoint_total for r in results)
    checkpoint_passed = sum(r.checkpoint_passed for r in results)

    retained_passed, retained_total = _retained_field_metric(results)
    correction_passed, correction_total = _family_metric(results, family="correction")
    supersession_passed, supersession_total = _supersession_metric(results)
    exclusion_passed, exclusion_total = _exclusion_persistence_metric(results)
    contradiction_passed, contradiction_total = _family_metric(results, family="contradiction")
    reference_passed, reference_total = _reference_resolution_metric(results)
    irrelevant_passed, irrelevant_total = _family_metric(results, family="irrelevant_info")

    by_split: dict[str, list[ConversationResult]] = {}
    for r in results:
        by_split.setdefault(r.scenario.split, []).append(r)

    def _split_summary(split_results):
        split_evaluable = [r for r in split_results if r.evaluable]
        return {
            "total": len(split_results),
            "evaluable": len(split_evaluable),
            "passed": sum(r.passed for r in split_evaluable),
            "pass_rate": _safe_rate(sum(r.passed for r in split_evaluable), len(split_evaluable)),
        }

    failure_taxonomy: dict[str, int] = {}
    for r in results:
        for check_name in r.failed_check_names():
            category = _checkpoint_taxonomy_category(r, check_name)
            failure_taxonomy[category] = failure_taxonomy.get(category, 0) + 1

    meta = {
        "run_id": run_id,
        "label": label,
        "corpus_version": CONVERSATION_CORPUS_VERSION,
        "git_sha": _git_sha(),
        "timestamp": timestamp.isoformat(),
        "conversation_count": len(results),
        "evaluable_count": len(evaluable),
        "infrastructure_failure_count": len(infrastructure_failures),
        "quality_pass_count": sum(r.passed for r in evaluable),
        "quality_pass_rate": _safe_rate(sum(r.passed for r in evaluable), len(evaluable)),
        "checkpoint_total": checkpoint_total,
        "checkpoint_passed": checkpoint_passed,
        "checkpoint_pass_rate": _safe_rate(checkpoint_passed, checkpoint_total),
        "cost": cost.to_json(),
        "failure_taxonomy": failure_taxonomy,
        "metrics": {
            "retained_field_accuracy": _safe_rate(retained_passed, retained_total),
            "retained_field_total": retained_total,
            "correction_accuracy": _safe_rate(correction_passed, correction_total),
            "correction_total": correction_total,
            "supersession_accuracy": _safe_rate(supersession_passed, supersession_total),
            "supersession_total": supersession_total,
            "exclusion_persistence_accuracy": _safe_rate(exclusion_passed, exclusion_total),
            "exclusion_persistence_total": exclusion_total,
            "contradiction_resolution_accuracy": _safe_rate(
                contradiction_passed, contradiction_total
            ),
            "contradiction_resolution_total": contradiction_total,
            "reference_resolution_accuracy": _safe_rate(reference_passed, reference_total),
            "reference_resolution_total": reference_total,
            "irrelevant_information_stability": _safe_rate(irrelevant_passed, irrelevant_total),
            "irrelevant_information_total": irrelevant_total,
        },
        "multilingual_continuity": _language_continuity_results(results),
        "by_split": {
            split: _split_summary(split_results) for split, split_results in by_split.items()
        },
        "by_family": {
            family: _split_summary([r for r in results if r.scenario.family == family])
            for family in sorted({r.scenario.family for r in results})
        },
    }
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    with open(run_dir / "results.jsonl", "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r.to_json()) + "\n")

    (run_dir / "summary.md").write_text(
        render_conversation_summary(meta, results), encoding="utf-8"
    )
    return run_dir


def render_conversation_summary(meta: dict, results: list[ConversationResult]) -> str:
    quality_rate = meta.get("quality_pass_rate")
    quality_rate_str = f"{quality_rate:.1%}" if quality_rate is not None else "n/a"
    lines = [
        "# Wanderes Multi-Turn Conversation Evaluation",
        "",
        f"- Run: `{meta['run_id']}`",
        f"- Corpus version: `{meta['corpus_version']}`",
        f"- Git commit: `{meta['git_sha']}`",
        f"- Conversations: {meta['conversation_count']} total, "
        f"{meta['evaluable_count']} evaluable, "
        f"{meta['infrastructure_failure_count']} infrastructure failure(s)",
        f"- Full-conversation pass rate: {meta['quality_pass_count']}/"
        f"{meta['evaluable_count']} ({quality_rate_str})",
        f"- Checkpoint pass rate: {meta['checkpoint_passed']}/{meta['checkpoint_total']}",
        f"- Estimated cost: ${meta['cost']['estimated_usd']} "
        f"({meta['cost']['pipeline_scenarios']} turn calls)",
        "",
        "## State-transition metrics",
        "",
    ]
    for label, key in (
        ("Retained-field accuracy", "retained_field_accuracy"),
        ("Correction accuracy", "correction_accuracy"),
        ("Supersession accuracy", "supersession_accuracy"),
        ("Exclusion-persistence accuracy", "exclusion_persistence_accuracy"),
        ("Contradiction-resolution accuracy", "contradiction_resolution_accuracy"),
        ("Reference-resolution accuracy", "reference_resolution_accuracy"),
        ("Irrelevant-information stability", "irrelevant_information_stability"),
    ):
        value = meta["metrics"][key]
        total_key = key.replace("accuracy", "total").replace("stability", "total")
        total = meta["metrics"].get(total_key, "?")
        rate_str = f"{value:.1%}" if value is not None else "n/a"
        lines.append(f"- {label}: {rate_str} (n={total})")
    lines.append("")

    lines.append("## Failure taxonomy")
    lines.append("")
    if meta["failure_taxonomy"]:
        for category, count in sorted(meta["failure_taxonomy"].items(), key=lambda kv: -kv[1]):
            lines.append(f"- {category}: {count}")
    else:
        lines.append("(no failures)")
    lines.append("")

    lines.append("## By split")
    lines.append("")
    for split, summary in sorted(meta["by_split"].items()):
        rate = f"{summary['pass_rate']:.1%}" if summary["pass_rate"] is not None else "n/a"
        lines.append(f"- {split}: {summary['passed']}/{summary['evaluable']} ({rate})")
    lines.append("")

    lines.append("## By family")
    lines.append("")
    for family, summary in sorted(meta["by_family"].items()):
        rate = f"{summary['pass_rate']:.1%}" if summary["pass_rate"] is not None else "n/a"
        lines.append(f"- {family}: {summary['passed']}/{summary['evaluable']} ({rate})")
    lines.append("")

    infra = [r for r in results if r.is_infrastructure_failure]
    if infra:
        lines.append("## Infrastructure failures (excluded from quality result above)")
        lines.append("")
        for r in infra[:50]:
            lines.append(
                f"- `{r.scenario.id}` ({r.scenario.family}): {r.infrastructure_failure_reason}"
            )
        lines.append("")

    quality_failed = [r for r in results if r.evaluable and not r.passed]
    if quality_failed:
        lines.append("## Failed conversations (quality)")
        lines.append("")
        for r in quality_failed[:50]:
            checks = ", ".join(r.failed_check_names())
            lines.append(f"- `{r.scenario.id}` ({r.scenario.family}): {checks}")
        lines.append("")

    return "\n".join(lines)


def load_conversation_run(run_dir: Path) -> tuple[dict, list[dict]]:
    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    results = []
    with open(run_dir / "results.jsonl", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                results.append(json.loads(line))
    return meta, results
