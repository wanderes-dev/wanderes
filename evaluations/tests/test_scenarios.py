import json
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from evaluations.scenarios import (
    Scenario,
    dev_scenarios,
    holdout_scenarios,
    load_corpus,
    metamorphic_pairs,
)


def _write_jsonl(scenarios: list[dict]) -> Path:
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8")
    for scenario in scenarios:
        tmp.write(json.dumps(scenario) + "\n")
    tmp.close()
    return Path(tmp.name)


def _minimal(id="T-1", split="dev", category="straightforward", **kwargs):
    payload = {"id": id, "split": split, "category": category, "message": "test"}
    payload.update(kwargs)
    return payload


class ScenarioValidationTests(SimpleTestCase):
    def test_invalid_split_raises(self):
        with self.assertRaises(ValueError):
            Scenario(id="T-1", split="bogus", category="straightforward", message="x")

    def test_invalid_category_raises(self):
        with self.assertRaises(ValueError):
            Scenario(id="T-1", split="dev", category="bogus", message="x")

    def test_invalid_flow_raises(self):
        with self.assertRaises(ValueError):
            Scenario(
                id="T-1",
                split="dev",
                category="straightforward",
                message="x",
                expected_flow="bogus",
            )

    def test_metamorphic_category_without_pair_id_raises(self):
        with self.assertRaises(ValueError):
            Scenario(id="T-1", split="dev", category="metamorphic", message="x")

    def test_valid_scenario_constructs_cleanly(self):
        scenario = Scenario(id="T-1", split="dev", category="straightforward", message="x")
        self.assertEqual(scenario.id, "T-1")


class LoadCorpusTests(SimpleTestCase):
    def test_loads_valid_jsonl(self):
        path = _write_jsonl([_minimal(), _minimal(id="T-2")])
        scenarios = load_corpus(path)
        self.assertEqual(len(scenarios), 2)

    def test_skips_blank_lines(self):
        path = _write_jsonl([_minimal()])
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n\n")
        scenarios = load_corpus(path)
        self.assertEqual(len(scenarios), 1)

    def test_duplicate_id_raises(self):
        path = _write_jsonl([_minimal(id="DUP"), _minimal(id="DUP")])
        with self.assertRaises(ValueError):
            load_corpus(path)

    def test_malformed_json_raises_with_line_number(self):
        path = _write_jsonl([_minimal()])
        with open(path, "a", encoding="utf-8") as f:
            f.write("{not valid json\n")
        with self.assertRaises(ValueError) as ctx:
            load_corpus(path)
        self.assertIn(":2:", str(ctx.exception))

    def test_round_trips_through_to_json_and_from_json(self):
        original = Scenario(
            id="T-1",
            split="dev",
            category="straightforward",
            message="x",
            expected_intent={"month": 7},
            must_not_include_slugs=("a", "b"),
        )
        restored = Scenario.from_json(original.to_json())
        self.assertEqual(original, restored)


class SplitHelpersTests(SimpleTestCase):
    def test_dev_and_holdout_partition_correctly(self):
        path = _write_jsonl([_minimal(id="D1", split="dev"), _minimal(id="H1", split="holdout")])
        scenarios = load_corpus(path)
        self.assertEqual([s.id for s in dev_scenarios(scenarios)], ["D1"])
        self.assertEqual([s.id for s in holdout_scenarios(scenarios)], ["H1"])


class MetamorphicPairsHelperTests(SimpleTestCase):
    def test_pairs_up_correctly(self):
        path = _write_jsonl(
            [
                _minimal(id="M1a", category="metamorphic", metamorphic_pair="P1"),
                _minimal(id="M1b", category="metamorphic", metamorphic_pair="P1"),
            ]
        )
        scenarios = load_corpus(path)
        pairs = metamorphic_pairs(scenarios)
        self.assertEqual(len(pairs), 1)
        self.assertEqual({pairs[0][0].id, pairs[0][1].id}, {"M1a", "M1b"})

    def test_unpaired_metamorphic_scenario_raises(self):
        path = _write_jsonl([_minimal(id="M1a", category="metamorphic", metamorphic_pair="P1")])
        scenarios = load_corpus(path)
        with self.assertRaises(ValueError):
            metamorphic_pairs(scenarios)
