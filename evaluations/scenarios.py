"""The evaluation corpus: a versioned, hand-authored set of synthetic
traveler scenarios, and the dataclass describing one.

A scenario carries ground truth at three independent layers, matching
the pipeline boundary this framework evaluates against
(natural-language -> intent extraction -> deterministic scoring ->
explanation):

- `expected_intent`: a partial dict of ai.orchestration.INTENT_SCHEMA
  fields. Only keys present are asserted - an omitted key means "not
  checked for this scenario", not "expected null". Lets one scenario
  focus on, say, budget extraction without also having to pin down
  exactly which month gets parsed.
- `deterministic_request`: a RecommendationRequest-shaped dict (month/
  min_temp_c/max_temp_c/max_cost_of_living/trip_type/continent/country/
  excluded_slugs). This is the scoring layer's ground truth, usable two
  ways: fed directly into recommendations.scoring.generate_recommendations
  with zero AI calls (deterministic-only mode), or compared against what
  the real pipeline's extracted intent produced (did extraction funnel
  into the same constraints scoring would need). None for scenarios that
  never reach scoring at all (accommodation/visa/off-topic/etc).
- Output-level fields (`must_not_include_slugs`, `acceptable_slugs`,
  `expects_*`) are the destination-level ground truth - deliberately not
  a single "expected destination", since most travel requests have more
  than one defensible answer (see documentation).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

CORPUS_DIR = Path(__file__).resolve().parent / "corpus"
CORPUS_PATH = CORPUS_DIR / "scenarios.jsonl"

# Bumped whenever scenario *semantics* change (a field's meaning, not
# just its count) - stored on every run artifact so an old run can never
# be silently compared against a corpus that no longer means the same
# thing. Adding new scenarios without changing existing ones does not
# require bumping this.
CORPUS_VERSION = "v1"

VALID_SPLITS = frozenset({"dev", "holdout"})

VALID_CATEGORIES = frozenset(
    {
        "straightforward",
        "ambiguous",
        "incomplete",
        "conflicting",
        "adversarial",
        "robustness",
        "metamorphic",
        "multi_turn",
    }
)

# Mirrors the orchestration branches enumerated in
# ai.orchestration.stream_travel_recommendation - which one a scenario's
# message should route into. Used to catch a scenario landing in the
# wrong branch entirely (e.g. an accommodation request misread as a
# fresh recommendation search) before any deeper check runs.
VALID_FLOWS = frozenset(
    {
        "recommendation",
        "accommodation",
        "accommodation_freeform",
        "visa",
        "booking",
        "video",
        "activity",
        "off_topic",
        "feedback",
        "future_intent",
        "recall",
    }
)


@dataclass(frozen=True)
class Scenario:
    id: str
    split: str
    category: str
    message: str
    expected_flow: str = "recommendation"
    notes: str = ""
    history: tuple[dict, ...] = ()
    profile_overrides: dict | None = None
    expected_intent: dict = field(default_factory=dict)
    deterministic_request: dict | None = None
    must_not_include_slugs: tuple[str, ...] = ()
    acceptable_slugs: tuple[str, ...] | None = None
    expects_recommendations: bool = True
    expects_clarification: bool = False
    expects_zero_results: bool = False
    metamorphic_pair: str | None = None
    metamorphic_axis: str | None = None
    metamorphic_expectation: str | None = None

    def __post_init__(self):
        if self.split not in VALID_SPLITS:
            raise ValueError(f"{self.id}: invalid split {self.split!r}")
        if self.category not in VALID_CATEGORIES:
            raise ValueError(f"{self.id}: invalid category {self.category!r}")
        if self.expected_flow not in VALID_FLOWS:
            raise ValueError(f"{self.id}: invalid expected_flow {self.expected_flow!r}")
        if self.category == "metamorphic" and not self.metamorphic_pair:
            raise ValueError(f"{self.id}: metamorphic scenario missing metamorphic_pair")

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "split": self.split,
            "category": self.category,
            "message": self.message,
            "expected_flow": self.expected_flow,
            "notes": self.notes,
            "history": list(self.history),
            "profile_overrides": self.profile_overrides,
            "expected_intent": self.expected_intent,
            "deterministic_request": self.deterministic_request,
            "must_not_include_slugs": list(self.must_not_include_slugs),
            "acceptable_slugs": (
                list(self.acceptable_slugs) if self.acceptable_slugs is not None else None
            ),
            "expects_recommendations": self.expects_recommendations,
            "expects_clarification": self.expects_clarification,
            "expects_zero_results": self.expects_zero_results,
            "metamorphic_pair": self.metamorphic_pair,
            "metamorphic_axis": self.metamorphic_axis,
            "metamorphic_expectation": self.metamorphic_expectation,
        }

    @classmethod
    def from_json(cls, data: dict) -> "Scenario":
        return cls(
            id=data["id"],
            split=data["split"],
            category=data["category"],
            message=data["message"],
            expected_flow=data.get("expected_flow", "recommendation"),
            notes=data.get("notes", ""),
            history=tuple(data.get("history") or ()),
            profile_overrides=data.get("profile_overrides"),
            expected_intent=data.get("expected_intent") or {},
            deterministic_request=data.get("deterministic_request"),
            must_not_include_slugs=tuple(data.get("must_not_include_slugs") or ()),
            acceptable_slugs=(
                tuple(data["acceptable_slugs"])
                if data.get("acceptable_slugs") is not None
                else None
            ),
            expects_recommendations=data.get("expects_recommendations", True),
            expects_clarification=data.get("expects_clarification", False),
            expects_zero_results=data.get("expects_zero_results", False),
            metamorphic_pair=data.get("metamorphic_pair"),
            metamorphic_axis=data.get("metamorphic_axis"),
            metamorphic_expectation=data.get("metamorphic_expectation"),
        )


def load_corpus(path: Path | None = None) -> list[Scenario]:
    """Load every scenario from the JSONL corpus file, in file order.

    Raises on a duplicate id or a scenario failing its own validation -
    a malformed corpus should never silently run a partial suite."""
    corpus_path = path or CORPUS_PATH
    scenarios = []
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
            scenario = Scenario.from_json(data)
            if scenario.id in seen_ids:
                raise ValueError(
                    f"{corpus_path}:{line_number}: duplicate scenario id {scenario.id!r}"
                )
            seen_ids.add(scenario.id)
            scenarios.append(scenario)
    return scenarios


def dev_scenarios(scenarios: list[Scenario] | None = None) -> list[Scenario]:
    scenarios = scenarios if scenarios is not None else load_corpus()
    return [s for s in scenarios if s.split == "dev"]


def holdout_scenarios(scenarios: list[Scenario] | None = None) -> list[Scenario]:
    scenarios = scenarios if scenarios is not None else load_corpus()
    return [s for s in scenarios if s.split == "holdout"]


def metamorphic_pairs(scenarios: list[Scenario] | None = None) -> list[tuple[Scenario, Scenario]]:
    """Pair up every scenario carrying a metamorphic_pair id with its
    partner. Each pair should appear exactly twice in the corpus (once
    per side of the axis being varied) - raises if a pair id doesn't
    resolve to exactly two scenarios, since an unpaired metamorphic
    scenario can't actually be evaluated."""
    scenarios = scenarios if scenarios is not None else load_corpus()
    by_pair: dict[str, list[Scenario]] = {}
    for s in scenarios:
        if s.metamorphic_pair:
            by_pair.setdefault(s.metamorphic_pair, []).append(s)
    pairs = []
    for pair_id, members in by_pair.items():
        if len(members) != 2:
            raise ValueError(
                f"metamorphic pair {pair_id!r} has {len(members)} members, expected exactly 2"
            )
        pairs.append((members[0], members[1]))
    return pairs
