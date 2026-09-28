"""Machine-verifiable checks specific to a multi-turn conversation - state
comparison at a checkpoint turn, reference resolution against what was
actually shown earlier (never a pre-authored assumption), exclusion
persistence, and stale-state resurrection. Reuses evaluations.intent_eval's
own field-comparison semantics (_values_match) rather than reimplementing
them, so a float/list/None comparison behaves identically to the
single-request corpus.

Grounding (evaluations.grounding) and the structural ranking-independence
check (evaluations.invariants.check_no_affiliate_or_acquisition_signal_in_scoring)
are reused as-is on the final turn's reply/scored set - a conversation is
not a reason to duplicate either.
"""

from __future__ import annotations

from dataclasses import dataclass

from evaluations.destination_equivalence import mentions_destination
from evaluations.intent_eval import FieldComparison, _values_match

from .conversation_scenarios import ConversationScenario

# The real RecommendationRequest-shaped fields a checkpoint can assert -
# anything else in expected_state is a corpus-authoring mistake, caught by
# evaluations.tests.test_conversation_scenarios rather than silently
# ignored here.
CHECKPOINT_FIELDS = (
    "month",
    "min_temp_c",
    "max_temp_c",
    "max_cost_of_living",
    "trip_type",
    "continent",
    "country",
    "excluded_slugs",
)


@dataclass(frozen=True)
class CheckpointResult:
    turn_index: int
    comparisons: tuple[FieldComparison, ...]

    @property
    def all_match(self) -> bool:
        return all(c.matches for c in self.comparisons)

    def to_json(self) -> dict:
        return {
            "turn_index": self.turn_index,
            "comparisons": [
                {"field": c.field, "expected": c.expected, "actual": c.actual, "matches": c.matches}
                for c in self.comparisons
            ],
        }


def build_actual_state(intent: dict, *, excluded_slugs: list[str]) -> dict:
    """The real, structured state a given turn's extraction actually
    produced, in the same field shape as a checkpoint's expected_state -
    excluded_slugs is passed in already resolved (the caller mirrors
    ai.orchestration's own find_destination_slugs_by_name resolution),
    since intent itself only ever carries excluded_place_names (raw
    text), never slugs."""
    return {
        "month": intent.get("month"),
        "min_temp_c": intent.get("min_temp_c"),
        "max_temp_c": intent.get("max_temp_c"),
        "max_cost_of_living": intent.get("max_cost_of_living"),
        "trip_type": intent.get("trip_type"),
        "continent": intent.get("continent"),
        "country": intent.get("country"),
        "excluded_slugs": sorted(excluded_slugs),
    }


def evaluate_checkpoint(
    expected_state: dict, actual_state: dict, *, turn_index: int
) -> CheckpointResult:
    comparisons = tuple(
        FieldComparison(
            field=field_name,
            expected=expected_value,
            actual=actual_state.get(field_name),
            matches=_values_match(expected_value, actual_state.get(field_name)),
        )
        for field_name, expected_value in expected_state.items()
    )
    return CheckpointResult(turn_index=turn_index, comparisons=comparisons)


def classify_checkpoint_mismatch(
    scenario: ConversationScenario, *, field_name: str, turn_index: int, actual_value
) -> str:
    """For one failed checkpoint field, decides whether it looks like
    STALE_STATE (the wrong value matches an earlier, already-superseded
    checkpoint's value for this same field) or LOST_CONTEXT (an earlier,
    still-active checkpoint had asserted a real value for this field, and
    it reverted to null/empty without ever being superseded) - falling
    back to a plain miss when neither pattern fits. Only looks at
    checkpoints strictly before this turn; a checkpoint has to have
    existed to be "superseded" or "lost" in the first place."""
    earlier_checkpoints = [
        (i, t.expected_state)
        for i, t in enumerate(scenario.turns)
        if i < turn_index and t.expected_state is not None and field_name in t.expected_state
    ]
    if not earlier_checkpoints:
        return "checkpoint_state_mismatch"

    most_recent_index, most_recent_state = earlier_checkpoints[-1]
    most_recent_value = most_recent_state[field_name]

    # STALE_STATE: the field was explicitly superseded/removed (set null)
    # at some earlier checkpoint, and actual_value matches a value from
    # BEFORE that supersession - the old preference is haunting a later
    # turn instead of staying gone.
    for i, state in earlier_checkpoints:
        if state[field_name] is None:
            continue
        was_superseded_later = any(
            j > i and t.expected_state is not None and t.expected_state.get(field_name) is None
            for j, t in enumerate(scenario.turns)
            if j < turn_index
        )
        if was_superseded_later and _values_match(state[field_name], actual_value):
            return "stale_state"

    # LOST_CONTEXT: the most recent checkpoint before this one asserted a
    # real (non-null) value for this field, nothing since superseded it,
    # and it now reads as null/empty - the value simply evaporated.
    if most_recent_value is not None and actual_value in (None, [], ()):
        return "lost_context"

    return "checkpoint_state_mismatch"


def check_exclusion_persistence(
    scenario: ConversationScenario, checkpoints: dict[int, CheckpointResult]
) -> list[tuple[int, str]]:
    """A slug asserted as excluded at some checkpoint must still be
    excluded at every LATER checkpoint that itself asserts excluded_slugs
    - authoring convention: once a checkpoint lists a slug, every later
    checkpoint that checks excluded_slugs at all should keep listing it
    unless the scenario explicitly reverses the exclusion (a real,
    intentional case gets its own expected_state without that slug, which
    is a corpus-authoring choice, not something this check second-guesses).
    Returns (turn_index, slug) pairs for a slug that dropped out."""
    violations = []
    seen_excluded: set[str] = set()
    for turn_index in sorted(checkpoints):
        result = checkpoints[turn_index]
        excluded_comparison = next(
            (c for c in result.comparisons if c.field == "excluded_slugs"), None
        )
        if excluded_comparison is None:
            continue
        expected_now = set(excluded_comparison.expected or [])
        actual_now = set(excluded_comparison.actual or [])
        missing = (seen_excluded & expected_now) - actual_now
        for slug in missing:
            violations.append((turn_index, slug))
        seen_excluded |= expected_now
    return violations


def resolve_reference(*, referenced_scored_slugs: list[str], ordinal: int) -> str | None:
    """The real slug shown at position `ordinal` (1-based) in an earlier
    turn's ACTUAL recorded scored list - never a pre-authored assumption
    about what would be shown, per the corpus design requirement."""
    index = ordinal - 1
    if 0 <= index < len(referenced_scored_slugs):
        return referenced_scored_slugs[index]
    return None


def check_reference_resolved(*, reply: str, destination) -> bool:
    """Whether a turn's reply engages with the real, specific destination
    a reference ("the second option") actually resolves to - reuses the
    same destination-name-equivalence matching (diacritics, the small
    hand-verified exonym table, whole-word only) the single-request
    corpus's winner_mentioned check already relies on, so a reference
    written in Portuguese or with an accented spelling isn't penalized
    for something normalization already handles generically. `destination`
    is the real travel.models.Destination the reference resolved to."""
    return mentions_destination(
        reply, slug=destination.slug, name=destination.name, country=destination.country
    )
