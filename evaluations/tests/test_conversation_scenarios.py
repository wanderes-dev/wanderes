import json
from pathlib import Path

from django.test import SimpleTestCase

from evaluations.conversation_scenarios import (
    VALID_FAMILIES,
    ConversationScenario,
    ConversationTurn,
    conversation_metamorphic_pairs,
    dev_conversations,
    holdout_conversations,
    load_conversation_corpus,
)

CATALOG_PATH = (
    Path(__file__).resolve().parent.parent.parent / "travel" / "data" / "curated_destinations.json"
)


def _real_slugs() -> set[str]:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return {entry["slug"] for entry in data["destinations"]}


def _turn(**kwargs):
    defaults = {"message": "hi"}
    defaults.update(kwargs)
    return ConversationTurn(**defaults)


class ConversationTurnTests(SimpleTestCase):
    def test_rejects_invalid_transition_label(self):
        with self.assertRaises(ValueError):
            _turn(expected_transitions={"trip_type": "not_a_real_label"})

    def test_rejects_ordinal_without_turn_index(self):
        with self.assertRaises(ValueError):
            _turn(references_ordinal=2)

    def test_round_trips_through_json(self):
        turn = _turn(
            message="quero praia",
            language="pt",
            expected_state={"trip_type": "beach"},
            expected_transitions={"trip_type": "added"},
        )
        restored = ConversationTurn.from_json(turn.to_json())
        self.assertEqual(turn, restored)


class ConversationScenarioTests(SimpleTestCase):
    def test_rejects_invalid_family(self):
        with self.assertRaises(ValueError):
            ConversationScenario(
                id="X-1", split="dev", family="not_a_family", turns=(_turn(), _turn())
            )

    def test_rejects_too_few_turns(self):
        with self.assertRaises(ValueError):
            ConversationScenario(id="X-1", split="dev", family="drift", turns=(_turn(),))

    def test_rejects_reference_to_a_later_turn(self):
        with self.assertRaises(ValueError):
            ConversationScenario(
                id="X-1",
                split="dev",
                family="reference",
                turns=(_turn(), _turn(references_turn_index=1)),
            )

    def test_checkpoint_turn_indices(self):
        scenario = ConversationScenario(
            id="X-1",
            split="dev",
            family="drift",
            turns=(_turn(), _turn(expected_state={"trip_type": "beach"}), _turn()),
        )
        self.assertEqual(scenario.checkpoint_turn_indices, [1])

    def test_round_trips_through_json(self):
        scenario = ConversationScenario(
            id="X-1",
            split="holdout",
            family="correction",
            turns=(_turn(message="a"), _turn(message="b", expected_state={"month": 10})),
        )
        restored = ConversationScenario.from_json(scenario.to_json())
        self.assertEqual(scenario, restored)


class RealCorpusTests(SimpleTestCase):
    """Validates the actual committed corpus, same spirit as
    evaluations.tests.test_corpus for the single-request corpus - fails
    loudly in CI the moment the corpus and the real catalog drift apart."""

    def test_loads_without_error(self):
        conversations = load_conversation_corpus()
        self.assertGreater(len(conversations), 0)

    def test_every_family_represented(self):
        conversations = load_conversation_corpus()
        families = {c.family for c in conversations}
        self.assertEqual(
            families, VALID_FAMILIES - {"cross_family"} | ({"cross_family"} & families)
        )
        for family in (
            "drift",
            "correction",
            "contradiction",
            "reference",
            "memory",
            "irrelevant_info",
        ):
            self.assertIn(family, families, f"no conversation tagged {family!r}")

    def test_every_referenced_slug_exists_in_the_real_catalog(self):
        real_slugs = _real_slugs()
        conversations = load_conversation_corpus()
        for conversation in conversations:
            for turn in conversation.turns:
                if turn.expected_state is None:
                    continue
                for slug in turn.expected_state.get("excluded_slugs") or []:
                    self.assertIn(
                        slug, real_slugs, f"{conversation.id}: {slug!r} is not a real catalog slug"
                    )

    def test_dev_holdout_split_is_roughly_85_15(self):
        conversations = load_conversation_corpus()
        dev = dev_conversations(conversations)
        holdout = holdout_conversations(conversations)
        self.assertEqual(len(dev) + len(holdout), len(conversations))
        holdout_share = len(holdout) / len(conversations)
        self.assertLess(holdout_share, 0.25, "holdout share drifted well past the intended ~15%")
        self.assertGreater(holdout_share, 0.05, "holdout share is too thin to catch overfitting")

    def test_metamorphic_pairs_resolve_cleanly(self):
        conversations = load_conversation_corpus()
        pairs = conversation_metamorphic_pairs(conversations)
        self.assertGreater(len(pairs), 0)

    def test_mtt_010_is_represented(self):
        conversations = load_conversation_corpus()
        found = any(
            "cidade no japao" in turn.message.lower() and "toquio" in turn.message.lower()
            for c in conversations
            for turn in c.turns
        )
        self.assertTrue(found, "MTT-010's message must be represented in the memory family")


class HistoricalArtifactsUntouchedTests(SimpleTestCase):
    """The Cycle 2 corpus/framework must never touch the existing
    single-request corpus or its historical run directories - a separate
    evaluation dimension, built additively."""

    def test_single_request_corpus_is_unaffected(self):
        from evaluations.scenarios import load_corpus

        scenarios = load_corpus()
        self.assertEqual(len(scenarios), 150, "Cycle 1's 150-scenario corpus must stay frozen")

    def test_conversation_corpus_writes_to_its_own_file(self):
        from evaluations.conversation_scenarios import CORPUS_PATH as CONVERSATION_CORPUS_PATH
        from evaluations.scenarios import CORPUS_PATH as SCENARIO_CORPUS_PATH

        self.assertNotEqual(CONVERSATION_CORPUS_PATH, SCENARIO_CORPUS_PATH)
        self.assertEqual(CONVERSATION_CORPUS_PATH.name, "conversations.jsonl")
        self.assertEqual(SCENARIO_CORPUS_PATH.name, "scenarios.jsonl")

    def test_historical_baseline_runs_still_exist_and_are_unmodified(self):
        import json

        from evaluations.persistence import RUNS_DIR

        for run_id in (
            "20260925-114531_baseline",
            "20260925-142147_cycle1",
            "20260925-155531_cycle1_verified",
        ):
            run_dir = RUNS_DIR / run_id
            self.assertTrue(run_dir.exists(), f"{run_id} must remain committed and untouched")
            meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["run_id"], run_id)
