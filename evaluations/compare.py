"""Compares two saved evaluation run artifacts and reports what actually
changed - newly fixed scenarios, newly broken scenarios, unchanged
failures, pass-rate deltas. A change that fixes 8 scenarios but breaks
20 should be obvious from this output, not something reconstructed by
eye from two separate summaries.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .persistence import load_run


@dataclass(frozen=True)
class RunDiff:
    baseline_run_id: str
    candidate_run_id: str
    newly_fixed: tuple[str, ...]
    newly_broken: tuple[str, ...]
    still_failing: tuple[str, ...]
    still_passing_count: int
    baseline_pass_rate: float
    candidate_pass_rate: float
    baseline_only_ids: tuple[str, ...]
    candidate_only_ids: tuple[str, ...]

    def render(self) -> str:
        lines = [
            f"# Evaluation comparison: {self.baseline_run_id} -> {self.candidate_run_id}",
            "",
            f"- Baseline pass rate: {self.baseline_pass_rate:.1%}",
            f"- Candidate pass rate: {self.candidate_pass_rate:.1%}",
            f"- Newly fixed: {len(self.newly_fixed)}",
            f"- Newly broken: {len(self.newly_broken)}",
            f"- Still failing (both runs): {len(self.still_failing)}",
            f"- Still passing (both runs): {self.still_passing_count}",
            "",
        ]
        if self.newly_broken:
            lines.append("## Newly broken - regressions, look here first")
            lines.extend(f"- {sid}" for sid in self.newly_broken)
            lines.append("")
        if self.newly_fixed:
            lines.append("## Newly fixed")
            lines.extend(f"- {sid}" for sid in self.newly_fixed)
            lines.append("")
        if self.still_failing:
            lines.append("## Still failing in both runs")
            lines.extend(f"- {sid}" for sid in self.still_failing)
            lines.append("")
        if self.baseline_only_ids or self.candidate_only_ids:
            lines.append("## Corpus changed between runs")
            if self.baseline_only_ids:
                lines.append(f"- Removed since baseline: {list(self.baseline_only_ids)}")
            if self.candidate_only_ids:
                lines.append(f"- Added since baseline: {list(self.candidate_only_ids)}")
            lines.append("")
        return "\n".join(lines)


def compare_runs(baseline_dir: Path, candidate_dir: Path) -> RunDiff:
    baseline_meta, baseline_results = load_run(baseline_dir)
    candidate_meta, candidate_results = load_run(candidate_dir)

    baseline_by_id = {r["id"]: r for r in baseline_results}
    candidate_by_id = {r["id"]: r for r in candidate_results}
    common_ids = set(baseline_by_id) & set(candidate_by_id)

    newly_fixed = tuple(
        sorted(
            sid
            for sid in common_ids
            if not baseline_by_id[sid]["passed"] and candidate_by_id[sid]["passed"]
        )
    )
    newly_broken = tuple(
        sorted(
            sid
            for sid in common_ids
            if baseline_by_id[sid]["passed"] and not candidate_by_id[sid]["passed"]
        )
    )
    still_failing = tuple(
        sorted(
            sid
            for sid in common_ids
            if not baseline_by_id[sid]["passed"] and not candidate_by_id[sid]["passed"]
        )
    )
    still_passing_count = sum(
        1 for sid in common_ids if baseline_by_id[sid]["passed"] and candidate_by_id[sid]["passed"]
    )

    return RunDiff(
        baseline_run_id=baseline_meta["run_id"],
        candidate_run_id=candidate_meta["run_id"],
        newly_fixed=newly_fixed,
        newly_broken=newly_broken,
        still_failing=still_failing,
        still_passing_count=still_passing_count,
        baseline_pass_rate=baseline_meta["pass_count"] / baseline_meta["scenario_count"],
        candidate_pass_rate=candidate_meta["pass_count"] / candidate_meta["scenario_count"],
        baseline_only_ids=tuple(sorted(set(baseline_by_id) - set(candidate_by_id))),
        candidate_only_ids=tuple(sorted(set(candidate_by_id) - set(baseline_by_id))),
    )
