"""Validates the corpus file itself - not any scenario's outcome, just
that scenarios.jsonl is well-formed and every real-world fact it
references (a slug) still exists in the actual catalog. Fast, no AI, no
DB - this is exactly the kind of check that should fail loudly in CI the
moment build_corpus.py and the real catalog drift apart, rather than
silently producing scenarios about destinations that no longer exist.
"""

import json
from pathlib import Path

from django.test import SimpleTestCase

from evaluations.scenarios import (
    VALID_CATEGORIES,
    VALID_FLOWS,
    VALID_SPLITS,
    load_corpus,
    metamorphic_pairs,
)

CATALOG_PATH = (
    Path(__file__).resolve().parent.parent.parent / "travel" / "data" / "curated_destinations.json"
)


def _real_slugs() -> set[str]:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return {entry["slug"] for entry in data["destinations"]}


class CorpusLoadsCleanlyTests(SimpleTestCase):
    def test_loads_without_error(self):
        scenarios = load_corpus()
        self.assertGreater(len(scenarios), 0)

    def test_scenario_count_within_intended_range(self):
        # The spec's own target: "approximately 100-200 scenarios."
        scenarios = load_corpus()
        self.assertGreaterEqual(len(scenarios), 100)
        self.assertLessEqual(len(scenarios), 200)

    def test_every_id_is_unique(self):
        scenarios = load_corpus()
        ids = [s.id for s in scenarios]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_split_is_valid(self):
        for scenario in load_corpus():
            self.assertIn(scenario.split, VALID_SPLITS)

    def test_every_category_is_valid(self):
        for scenario in load_corpus():
            self.assertIn(scenario.category, VALID_CATEGORIES)

    def test_every_flow_is_valid(self):
        for scenario in load_corpus():
            self.assertIn(scenario.expected_flow, VALID_FLOWS)

    def test_holdout_split_is_a_meaningful_fraction(self):
        scenarios = load_corpus()
        holdout_count = sum(1 for s in scenarios if s.split == "holdout")
        # Not pinned to an exact ratio - just guards against the holdout
        # set silently shrinking to near-nothing (or the whole corpus).
        self.assertGreater(holdout_count, 10)
        self.assertLess(holdout_count, len(scenarios))

    def test_every_deterministic_request_has_a_month(self):
        # recommendations.scoring.RecommendationRequest.month is a
        # required field with no default (climate can't be looked up
        # without one) - a deterministic_request missing it isn't caught
        # by Scenario's own validation (it's a plain dict, not a
        # RecommendationRequest) and only surfaces as a raw KeyError deep
        # inside evaluations.requests.build_request the first time
        # someone actually runs that scenario. Caught here instead, at
        # corpus-build time (regression case: STR-049 was missing this).
        for scenario in load_corpus():
            if scenario.deterministic_request is not None:
                self.assertIn(
                    "month", scenario.deterministic_request, f"{scenario.id} has no month"
                )

    def test_every_category_has_at_least_one_scenario(self):
        scenarios = load_corpus()
        present = {s.category for s in scenarios}
        self.assertEqual(present, VALID_CATEGORIES)


class CorpusReferencesRealDestinationsTests(SimpleTestCase):
    """The one check that actually cross-references build_corpus.py's
    hand-typed slugs against the real catalog file - catches a typo'd
    slug or a destination later removed/renamed from the dataset."""

    def setUp(self):
        self.real_slugs = _real_slugs()
        self.scenarios = load_corpus()

    def test_must_not_include_slugs_are_real(self):
        for scenario in self.scenarios:
            for slug in scenario.must_not_include_slugs:
                self.assertIn(
                    slug,
                    self.real_slugs,
                    f"{scenario.id}: must_not_include_slugs has bad slug {slug!r}",
                )

    def test_acceptable_slugs_are_real(self):
        for scenario in self.scenarios:
            if scenario.acceptable_slugs is None:
                continue
            for slug in scenario.acceptable_slugs:
                self.assertIn(
                    slug, self.real_slugs, f"{scenario.id}: acceptable_slugs has bad slug {slug!r}"
                )

    def test_deterministic_request_excluded_slugs_are_real(self):
        for scenario in self.scenarios:
            if scenario.deterministic_request is None:
                continue
            for slug in scenario.deterministic_request.get("excluded_slugs") or ():
                self.assertIn(
                    slug, self.real_slugs, f"{scenario.id}: excluded_slugs has bad slug {slug!r}"
                )

    def test_profile_override_slugs_are_real(self):
        for scenario in self.scenarios:
            overrides = scenario.profile_overrides or {}
            for key in ("completed_trip_slugs", "travel_history_slugs"):
                for slug in overrides.get(key) or ():
                    self.assertIn(
                        slug, self.real_slugs, f"{scenario.id}: {key} has bad slug {slug!r}"
                    )


class MetamorphicPairsResolveTests(SimpleTestCase):
    def test_every_metamorphic_scenario_has_exactly_one_partner(self):
        # metamorphic_pairs() itself raises if any pair id doesn't
        # resolve to exactly 2 members - calling it is the test.
        pairs = metamorphic_pairs()
        self.assertGreater(len(pairs), 0)

    def test_every_metamorphic_category_scenario_declares_a_pair_id(self):
        for scenario in load_corpus():
            if scenario.category == "metamorphic":
                self.assertIsNotNone(scenario.metamorphic_pair, f"{scenario.id} has no pair id")

    def test_monotonic_axis_pairs_both_have_deterministic_request(self):
        from evaluations.metamorphic import MONOTONIC_AXES

        for scenario_a, scenario_b in metamorphic_pairs():
            axis = scenario_a.metamorphic_axis or scenario_b.metamorphic_axis
            if axis in MONOTONIC_AXES:
                self.assertIsNotNone(scenario_a.deterministic_request, scenario_a.id)
                self.assertIsNotNone(scenario_b.deterministic_request, scenario_b.id)
