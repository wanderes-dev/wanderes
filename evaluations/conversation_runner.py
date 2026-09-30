"""Drives one ConversationScenario through the real production
orchestration path - ai.orchestration.stream_travel_recommendation(),
called once per turn with a real, persistent session_key so the actual
Redis-backed conv_key mechanism (ai.memory) fires exactly as it does for
a live traveler. Deliberately never uses history_override: Cycle 1's own
evaluator uses it for single-request scenarios, but history_override
forces conv_key=None (ai.orchestration.stream_travel_recommendation),
which skips the climate/budget accumulator and the profile-confirmation
gate entirely - exactly the two pieces of real persistent state this
corpus exists to exercise. See documentation/18_CONVERSATION_EVALUATION_FRAMEWORK.md
§2 for the full architecture trace this was based on.

No special evaluation-only conversation engine exists here - every call
below goes through the same entry point, the same intent extraction, the
same scoring, the same explanation generation a real /chat/ request uses.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from ai import memory
from ai.orchestration import stream_travel_recommendation
from ai.provider import AIProvider, AIProviderError
from recommendations.scoring import ScoredDestination
from travel.services import find_destination_slugs_by_name

from .conversation_invariants import (
    CheckpointResult,
    build_actual_state,
    check_exclusion_persistence,
    check_reference_resolved,
    classify_checkpoint_mismatch,
    evaluate_checkpoint,
    resolve_reference,
)
from .conversation_scenarios import ConversationScenario
from .cost import CostTracker
from .grounding import GroundingResult, run_grounding_checks
from .invariants import InvariantResult, check_no_affiliate_or_acquisition_signal_in_scoring
from .profiles import synthetic_traveler
from .weather_fixtures import MissingWeatherFixtureError


@dataclass
class TurnResult:
    turn_index: int
    message: str
    reply: str = ""
    intent: dict = field(default_factory=dict)
    # The accumulated state as persisted after this turn (ai.orchestration's
    # state_sink) - what checkpoints assert on, as opposed to `intent`,
    # which is only what this one message's extraction yielded.
    effective_state: dict = field(default_factory=dict)
    scored_slugs: list[str] = field(default_factory=list)
    checkpoint: CheckpointResult | None = None
    reference_resolved: bool | None = None  # None when the turn isn't a reference turn
    reference_target_slug: str | None = None
    clarification_expected: bool = False
    clarification_observed: bool = False  # true if this turn actually produced zero recommendations

    def to_json(self) -> dict:
        return {
            "turn_index": self.turn_index,
            "message": self.message,
            "reply": self.reply,
            "intent": self.intent,
            "effective_state": self.effective_state,
            "scored_slugs": self.scored_slugs,
            "checkpoint": self.checkpoint.to_json() if self.checkpoint else None,
            "reference_resolved": self.reference_resolved,
            "reference_target_slug": self.reference_target_slug,
            "clarification_expected": self.clarification_expected,
            "clarification_observed": self.clarification_observed,
        }


@dataclass
class ConversationResult:
    scenario: ConversationScenario
    turns: list[TurnResult] = field(default_factory=list)
    exclusion_violations: list[tuple[int, str]] = field(default_factory=list)
    stale_state_findings: list[tuple[int, str]] = field(default_factory=list)  # (turn_index, field)
    lost_context_findings: list[tuple[int, str]] = field(default_factory=list)
    grounding: list[GroundingResult] = field(default_factory=list)
    ranking_independence: InvariantResult | None = None
    error: str | None = None
    latency_ms: float = 0.0
    is_infrastructure_failure: bool = False
    infrastructure_failure_reason: str | None = None
    first_divergence_turn: int | None = None

    @property
    def evaluable(self) -> bool:
        return not self.is_infrastructure_failure

    @property
    def checkpoints(self) -> list[TurnResult]:
        return [t for t in self.turns if t.checkpoint is not None]

    @property
    def checkpoint_total(self) -> int:
        return len(self.checkpoints)

    @property
    def checkpoint_passed(self) -> int:
        return sum(1 for t in self.checkpoints if t.checkpoint.all_match)

    @property
    def reference_turns(self) -> list[TurnResult]:
        return [t for t in self.turns if t.reference_resolved is not None]

    @property
    def passed(self) -> bool:
        if self.is_infrastructure_failure or self.error is not None:
            return False
        if any(not t.checkpoint.all_match for t in self.checkpoints):
            return False
        if any(t.reference_resolved is False for t in self.turns):
            return False
        if self.exclusion_violations or self.stale_state_findings or self.lost_context_findings:
            return False
        if not all(r.passed for r in self.grounding):
            return False
        if self.ranking_independence is not None and not self.ranking_independence.passed:
            return False
        return True

    def failed_check_names(self) -> list[str]:
        if self.is_infrastructure_failure:
            return ["dependency_failure"]
        names = []
        if self.error is not None:
            names.append("error")
        for t in self.checkpoints:
            names += [
                f"checkpoint_state:{c.field}" for c in t.checkpoint.comparisons if not c.matches
            ]
        if any(t.reference_resolved is False for t in self.turns):
            names.append("reference_resolved")
        if self.exclusion_violations:
            names.append("exclusion_still_persists")
        if self.stale_state_findings:
            names.append("no_stale_state_resurrection")
        if self.lost_context_findings:
            names.append("no_lost_context")
        names += [r.name for r in self.grounding if not r.passed]
        if self.ranking_independence is not None and not self.ranking_independence.passed:
            names.append(self.ranking_independence.name)
        return names

    def to_json(self) -> dict:
        return {
            "id": self.scenario.id,
            "split": self.scenario.split,
            "family": self.scenario.family,
            "passed": self.passed,
            "evaluable": self.evaluable,
            "is_infrastructure_failure": self.is_infrastructure_failure,
            "infrastructure_failure_reason": self.infrastructure_failure_reason,
            "error": self.error,
            "latency_ms": self.latency_ms,
            "turn_count": len(self.scenario.turns),
            "turns": [t.to_json() for t in self.turns],
            "checkpoint_total": self.checkpoint_total,
            "checkpoint_passed": self.checkpoint_passed,
            "exclusion_violations": [
                {"turn_index": i, "slug": slug} for i, slug in self.exclusion_violations
            ],
            "stale_state_findings": [
                {"turn_index": i, "field": f} for i, f in self.stale_state_findings
            ],
            "lost_context_findings": [
                {"turn_index": i, "field": f} for i, f in self.lost_context_findings
            ],
            "grounding": [
                {"name": r.name, "passed": r.passed, "detail": r.detail} for r in self.grounding
            ],
            "ranking_independence": (
                {
                    "passed": self.ranking_independence.passed,
                    "detail": self.ranking_independence.detail,
                }
                if self.ranking_independence
                else None
            ),
            "first_divergence_turn": self.first_divergence_turn,
            "failed_checks": self.failed_check_names(),
        }

    def render_trace(self) -> str:
        """Developer-readable per-turn trace - never shown to a real
        traveler, dev diagnostics only (mirrors evaluations.trace's own
        framing for the single-request corpus)."""
        lines = [f"Conversation {self.scenario.id} ({self.scenario.family})"]
        for t in self.turns:
            lines.append(f"\nTurn {t.turn_index + 1}")
            lines.append(f'  User: "{t.message}"')
            lines.append(f"  Extracted state: {t.intent}")
            lines.append(f"  Persisted state: {t.effective_state}")
            lines.append(f"  Scored: {t.scored_slugs}")
            if t.checkpoint:
                for c in t.checkpoint.comparisons:
                    mark = "OK" if c.matches else "MISMATCH"
                    lines.append(f"    [{mark}] {c.field}: expected={c.expected} actual={c.actual}")
            if t.reference_resolved is not None:
                mark = "OK" if t.reference_resolved else "UNRESOLVED"
                lines.append(f"    [{mark}] reference -> {t.reference_target_slug}")
        if self.first_divergence_turn is not None:
            lines.append(f"\nFirst divergence at turn {self.first_divergence_turn + 1}")
        return "\n".join(lines)


def run_conversation(
    scenario: ConversationScenario,
    *,
    ai_provider: AIProvider,
    climate_provider,
    cost: CostTracker,
    attempt: int = 0,
) -> ConversationResult:
    started_at = time.perf_counter()
    result = ConversationResult(scenario=scenario)
    scored_history: list[list[ScoredDestination]] = []

    with synthetic_traveler(scenario.id, scenario.profile_overrides) as user:
        session_key = None if user else f"eval-conv-{scenario.id}-{attempt}"
        conv_key = memory.conversation_key(user=user, session_key=session_key)
        memory.clear_history(conv_key)  # guarantee no leakage from a prior attempt

        for turn_index, turn in enumerate(scenario.turns):
            intent_sink: dict = {}
            state_sink: dict = {}
            try:
                streaming = stream_travel_recommendation(
                    turn.message,
                    user=user,
                    session_key=session_key,
                    ai_provider=ai_provider,
                    climate_provider=climate_provider,
                    intent_sink=intent_sink,
                    state_sink=state_sink,
                )
                reply = "".join(streaming.reply_chunks)
            except MissingWeatherFixtureError as exc:
                result.is_infrastructure_failure = True
                result.infrastructure_failure_reason = str(exc)
                result.first_divergence_turn = turn_index
                break
            except AIProviderError as exc:
                result.error = str(exc)
                result.first_divergence_turn = turn_index
                break

            scored = list(streaming.recommendations)
            scored_history.append(scored)
            cost.record_pipeline_call(scenario_message=turn.message, reply=reply)

            excluded_slugs = sorted(
                find_destination_slugs_by_name(state_sink.get("excluded_place_names") or [])
            )
            turn_result = TurnResult(
                turn_index=turn_index,
                message=turn.message,
                reply=reply,
                intent=dict(intent_sink),
                effective_state=dict(state_sink),
                scored_slugs=[s.destination.slug for s in scored],
            )

            if turn.expected_state is not None:
                actual_state = build_actual_state(
                    intent_sink, state_sink, excluded_slugs=excluded_slugs
                )
                checkpoint = evaluate_checkpoint(
                    turn.expected_state, actual_state, turn_index=turn_index
                )
                turn_result.checkpoint = checkpoint
                if not checkpoint.all_match and result.first_divergence_turn is None:
                    result.first_divergence_turn = turn_index
                for c in checkpoint.comparisons:
                    if c.matches:
                        continue
                    label = classify_checkpoint_mismatch(
                        scenario, field_name=c.field, turn_index=turn_index, actual_value=c.actual
                    )
                    if label == "stale_state":
                        result.stale_state_findings.append((turn_index, c.field))
                    elif label == "lost_context":
                        result.lost_context_findings.append((turn_index, c.field))

            if turn.references_turn_index is not None:
                referenced_scored = scored_history[turn.references_turn_index]
                target_slug = resolve_reference(
                    referenced_scored_slugs=[s.destination.slug for s in referenced_scored],
                    ordinal=turn.references_ordinal or 1,
                )
                turn_result.reference_target_slug = target_slug
                if target_slug is None:
                    # The referenced turn never actually produced that many
                    # options - not this turn's fault, so this counts as
                    # unresolved rather than a false reference_resolved=False.
                    turn_result.reference_resolved = None
                else:
                    target = next(
                        s.destination
                        for s in referenced_scored
                        if s.destination.slug == target_slug
                    )
                    turn_result.reference_resolved = check_reference_resolved(
                        reply=reply, destination=target
                    )
                    if (
                        turn_result.reference_resolved is False
                        and result.first_divergence_turn is None
                    ):
                        result.first_divergence_turn = turn_index

            if turn.expects_clarification:
                turn_result.clarification_expected = True
                turn_result.clarification_observed = len(scored) == 0

            result.turns.append(turn_result)

        checkpoints = {t.turn_index: t.checkpoint for t in result.turns if t.checkpoint is not None}
        if checkpoints:
            result.exclusion_violations = check_exclusion_persistence(scenario, checkpoints)

        if result.turns and not result.is_infrastructure_failure and result.error is None:
            last_turn = result.turns[-1]
            result.grounding = run_grounding_checks(last_turn.reply, scored_history[-1])
            result.ranking_independence = check_no_affiliate_or_acquisition_signal_in_scoring()

    result.latency_ms = (time.perf_counter() - started_at) * 1000
    return result


def select_conversations(
    conversations: list[ConversationScenario],
    *,
    split: str | None,
    family: str | None,
    scenario_id: str | None,
    sample: int | None,
    seed: int = 1337,
) -> list[ConversationScenario]:
    import random

    pool = [c for c in conversations if split is None or c.split == split]
    if family is not None:
        pool = [c for c in pool if c.family == family]
    if scenario_id is not None:
        pool = [c for c in pool if c.id == scenario_id]
    if sample is None or sample >= len(pool):
        return pool
    rng = random.Random(seed)
    return rng.sample(pool, sample)


def run_conversations(
    conversations: list[ConversationScenario],
    *,
    ai_provider: AIProvider,
    climate_provider=None,
) -> tuple[list[ConversationResult], CostTracker]:
    from django.conf import settings

    from .weather_fixtures import FixtureWeatherProvider

    climate_provider = climate_provider or FixtureWeatherProvider()
    cost = CostTracker(model_name=getattr(settings, "AI_MODEL", "unknown"))
    results = [
        run_conversation(c, ai_provider=ai_provider, climate_provider=climate_provider, cost=cost)
        for c in conversations
    ]
    return results, cost
