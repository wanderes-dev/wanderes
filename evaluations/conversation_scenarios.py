"""The multi-turn conversation corpus - a second, independent evaluation
dimension alongside evaluations.scenarios's single-request corpus (never
modified by this module or its corpus file).

Where evaluations.scenarios asks "given one message, does Wanderes
produce a sound recommendation," this corpus asks "across a real
conversation, does Wanderes keep a coherent, current understanding of
the traveler" - preference drift, corrections, contradictions,
references to what was already shown, long-range memory, and resistance
to conversational noise that shouldn't touch travel state at all.

A conversation is a sequence of ConversationTurn objects. Ground truth
lives at selected checkpoint turns as `expected_state` - a partial dict
using the *real* RecommendationRequest-shaped fields
(month/min_temp_c/max_temp_c/max_cost_of_living/trip_type/continent/
country/excluded_slugs), never an invented schema. An omitted field means
"not checked at this checkpoint," exactly like evaluations.scenarios's
own expected_intent convention - not "expected null." A field explicitly
set to None means "expected null right now" (a superseded/removed value),
which is how supersession and removal get asserted without a separate
mechanism.

`expected_transitions` is documentation only (retained/added/superseded/
removed/unresolved per field, at this checkpoint) - it doesn't drive any
check by itself; it makes the corpus and its trace output readable, and
lets the runner tell a STALE_STATE failure (actual matches an earlier,
already-superseded value) apart from a LOST_CONTEXT one (actual is
null/default when an unsuperseded earlier value should have carried
forward).

`references_turn_index`/`references_ordinal` support Family D (reference
resolution) without ever hardcoding which destination "the second option"
should be - the runner resolves this from the ACTUAL recorded scored list
of the referenced earlier turn, at run time.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

CORPUS_DIR = Path(__file__).resolve().parent / "corpus"
CORPUS_PATH = CORPUS_DIR / "conversations.jsonl"

# Bumped whenever a conversation's *semantics* change (not just corpus
# growth) - stored on every run artifact, same convention as
# evaluations.scenarios.CORPUS_VERSION, so an old run can never be
# silently compared against a corpus that no longer means the same thing.
CONVERSATION_CORPUS_VERSION = "v1"

VALID_SPLITS = frozenset({"dev", "holdout"})

VALID_FAMILIES = frozenset(
    {
        "drift",  # A: preference drift / change of mind
        "correction",  # B: corrections
        "contradiction",  # C: contradictions
        "reference",  # D: references to previous recommendations
        "memory",  # E: long-term conversational memory
        "irrelevant_info",  # F: irrelevant-information resistance
        "cross_family",  # multiple phenomena in one realistic conversation
    }
)

VALID_TRANSITIONS = frozenset({"retained", "added", "superseded", "removed", "unresolved"})


@dataclass(frozen=True)
class ConversationTurn:
    message: str
    language: str = "en"
    # None for a turn that's just conversational connective tissue with
    # nothing new to assert - most turns in a realistic conversation don't
    # need a checkpoint, only the ones that actually test something.
    expected_state: dict | None = None
    expected_transitions: dict | None = None  # field -> one of VALID_TRANSITIONS, doc-only
    # Set on a turn whose message refers back to an earlier turn's shown
    # options ("the second option", "something like the first one but
    # cheaper") - resolved against that turn's REAL recorded scored list
    # at run time, never against a pre-authored assumption of what would
    # be shown.
    references_turn_index: int | None = None
    references_ordinal: int | None = None  # 1-based ("the second one" -> 2)
    # True when the correct behavior is a clarifying question, not a
    # forced recommendation/interpretation - checked turns should not be
    # penalized for asking, only for inventing unsupported state.
    expects_clarification: bool = False
    notes: str = ""

    def __post_init__(self):
        if self.expected_transitions:
            bad = set(self.expected_transitions.values()) - VALID_TRANSITIONS
            if bad:
                raise ValueError(f"invalid transition label(s): {bad}")
        if self.references_ordinal is not None and self.references_turn_index is None:
            raise ValueError("references_ordinal set without references_turn_index")

    def to_json(self) -> dict:
        return {
            "message": self.message,
            "language": self.language,
            "expected_state": self.expected_state,
            "expected_transitions": self.expected_transitions,
            "references_turn_index": self.references_turn_index,
            "references_ordinal": self.references_ordinal,
            "expects_clarification": self.expects_clarification,
            "notes": self.notes,
        }

    @classmethod
    def from_json(cls, data: dict) -> "ConversationTurn":
        return cls(
            message=data["message"],
            language=data.get("language", "en"),
            expected_state=data.get("expected_state"),
            expected_transitions=data.get("expected_transitions"),
            references_turn_index=data.get("references_turn_index"),
            references_ordinal=data.get("references_ordinal"),
            expects_clarification=data.get("expects_clarification", False),
            notes=data.get("notes", ""),
        )


@dataclass(frozen=True)
class ConversationScenario:
    id: str
    split: str
    family: str
    turns: tuple[ConversationTurn, ...]
    profile_overrides: dict | None = None
    notes: str = ""
    metamorphic_pair: str | None = None
    metamorphic_axis: str | None = None

    def __post_init__(self):
        if self.split not in VALID_SPLITS:
            raise ValueError(f"{self.id}: invalid split {self.split!r}")
        if self.family not in VALID_FAMILIES:
            raise ValueError(f"{self.id}: invalid family {self.family!r}")
        if not (2 <= len(self.turns) <= 12):
            # A minimal correction/contradiction/drift case is genuinely
            # just two turns (a stated value, then the turn that changes
            # it) - the brief's own "€800 total" -> "sorry, per person"
            # example is exactly this shape. "Roughly 3-10" describes the
            # typical case, not a hard floor a real minimal example
            # shouldn't be padded to satisfy.
            raise ValueError(f"{self.id}: {len(self.turns)} turns - expected roughly 2-10")
        for i, turn in enumerate(self.turns):
            if turn.references_turn_index is not None and not (0 <= turn.references_turn_index < i):
                raise ValueError(
                    f"{self.id} turn {i}: references_turn_index {turn.references_turn_index} "
                    "must point at an earlier turn"
                )

    @property
    def checkpoint_turn_indices(self) -> list[int]:
        return [i for i, t in enumerate(self.turns) if t.expected_state is not None]

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "split": self.split,
            "family": self.family,
            "turns": [t.to_json() for t in self.turns],
            "profile_overrides": self.profile_overrides,
            "notes": self.notes,
            "metamorphic_pair": self.metamorphic_pair,
            "metamorphic_axis": self.metamorphic_axis,
        }

    @classmethod
    def from_json(cls, data: dict) -> "ConversationScenario":
        return cls(
            id=data["id"],
            split=data["split"],
            family=data["family"],
            turns=tuple(ConversationTurn.from_json(t) for t in data["turns"]),
            profile_overrides=data.get("profile_overrides"),
            notes=data.get("notes", ""),
            metamorphic_pair=data.get("metamorphic_pair"),
            metamorphic_axis=data.get("metamorphic_axis"),
        )


def load_conversation_corpus(path: Path | None = None) -> list[ConversationScenario]:
    corpus_path = path or CORPUS_PATH
    conversations = []
    seen_ids = set()
    with open(corpus_path, encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{corpus_path}:{line_number}: invalid JSON - {exc}") from exc
            conversation = ConversationScenario.from_json(data)
            if conversation.id in seen_ids:
                raise ValueError(
                    f"{corpus_path}:{line_number}: duplicate conversation id {conversation.id!r}"
                )
            seen_ids.add(conversation.id)
            conversations.append(conversation)
    return conversations


def dev_conversations(
    conversations: list[ConversationScenario] | None = None,
) -> list[ConversationScenario]:
    conversations = conversations if conversations is not None else load_conversation_corpus()
    return [c for c in conversations if c.split == "dev"]


def holdout_conversations(
    conversations: list[ConversationScenario] | None = None,
) -> list[ConversationScenario]:
    conversations = conversations if conversations is not None else load_conversation_corpus()
    return [c for c in conversations if c.split == "holdout"]


def conversation_metamorphic_pairs(
    conversations: list[ConversationScenario] | None = None,
) -> list[tuple[ConversationScenario, ConversationScenario]]:
    conversations = conversations if conversations is not None else load_conversation_corpus()
    by_pair: dict[str, list[ConversationScenario]] = {}
    for c in conversations:
        if c.metamorphic_pair:
            by_pair.setdefault(c.metamorphic_pair, []).append(c)
    pairs = []
    for pair_id, members in by_pair.items():
        if len(members) != 2:
            raise ValueError(
                f"conversation metamorphic pair {pair_id!r} has {len(members)} members, "
                "expected exactly 2"
            )
        pairs.append((members[0], members[1]))
    return pairs
