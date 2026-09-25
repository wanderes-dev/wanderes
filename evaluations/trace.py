"""Dev-only diagnostics: turns one generate_recommendations() call into a
human-inspectable trace (eligible count -> rejections -> scored
candidates -> winner). Never shown to a traveler, never imported by
production code - recommendations.scoring only exposes the plain `trace`
dict parameter this module consumes; it has no idea evaluations/ exists.
"""

from __future__ import annotations

from dataclasses import dataclass

from recommendations.scoring import (
    RecommendationRequest,
    ScoredDestination,
    generate_recommendations,
)


@dataclass(frozen=True)
class ScoredCandidateTrace:
    slug: str
    name: str
    score: float
    preference_fit: float
    budget_fit: float
    temperature_fit: float
    repetition_penalty: float
    avg_high_c: float | None


@dataclass(frozen=True)
class RecommendationTrace:
    eligible_after_hard_filters: int
    climate_errors: int
    temperature_rejected: int
    time_budget_exceeded: bool
    scored: tuple[ScoredCandidateTrace, ...]
    winning_slug: str | None

    def render(self) -> str:
        """Compact ASCII rendering for `--trace` CLI output - conceptually
        the "128 considered -> 74 rejected -> 54 scored -> X selected"
        shape, using the real numbers from this run."""
        lines = [
            f"{self.eligible_after_hard_filters} destination(s) eligible after hard constraints"
        ]
        if self.climate_errors:
            lines.append(f"  {self.climate_errors} skipped (climate lookup failed)")
        if self.temperature_rejected:
            lines.append(f"  {self.temperature_rejected} rejected on temperature")
        if self.time_budget_exceeded:
            lines.append("  climate lookup time budget exceeded - partial results only")
        lines.append(f"{len(self.scored)} scored")
        for c in self.scored[:10]:
            lines.append(
                f"  {c.name} ({c.slug}): score={c.score:.2f} "
                f"[pref={c.preference_fit:+.1f} budget={c.budget_fit:+.1f} "
                f"temp={c.temperature_fit:+.1f} repeat={-c.repetition_penalty:+.1f}]"
            )
        if len(self.scored) > 10:
            lines.append(f"  ... and {len(self.scored) - 10} more")
        if self.winning_slug:
            lines.append(f"-> {self.winning_slug} selected")
        elif self.eligible_after_hard_filters:
            lines.append("-> no destination survived scoring")
        return "\n".join(lines)

    def to_json(self) -> dict:
        return {
            "eligible_after_hard_filters": self.eligible_after_hard_filters,
            "climate_errors": self.climate_errors,
            "temperature_rejected": self.temperature_rejected,
            "time_budget_exceeded": self.time_budget_exceeded,
            "scored": [
                {
                    "slug": c.slug,
                    "name": c.name,
                    "score": c.score,
                    "preference_fit": c.preference_fit,
                    "budget_fit": c.budget_fit,
                    "temperature_fit": c.temperature_fit,
                    "repetition_penalty": c.repetition_penalty,
                    "avg_high_c": c.avg_high_c,
                }
                for c in self.scored[:10]
            ],
            "winning_slug": self.winning_slug,
        }


def trace_recommendations(
    request: RecommendationRequest, *, climate_provider=None
) -> tuple[list[ScoredDestination], RecommendationTrace]:
    """Run generate_recommendations with tracing on, returning both the
    normal ranked result (for invariant checks that need real
    ScoredDestination objects) and a serializable RecommendationTrace."""
    raw_trace: dict = {}
    scored = generate_recommendations(request, climate_provider=climate_provider, trace=raw_trace)
    scored_trace = tuple(
        ScoredCandidateTrace(
            slug=s.destination.slug,
            name=s.destination.name,
            score=s.score,
            preference_fit=s.preference_fit,
            budget_fit=s.budget_fit,
            temperature_fit=s.temperature_fit,
            repetition_penalty=s.repetition_penalty,
            avg_high_c=s.avg_high_c,
        )
        for s in scored
    )
    trace = RecommendationTrace(
        eligible_after_hard_filters=raw_trace.get("eligible_after_hard_filters", 0),
        climate_errors=raw_trace.get("climate_errors", 0),
        temperature_rejected=raw_trace.get("temperature_rejected", 0),
        time_budget_exceeded=raw_trace.get("time_budget_exceeded", False),
        scored=scored_trace,
        winning_slug=scored[0].destination.slug if scored else None,
    )
    return scored, trace
