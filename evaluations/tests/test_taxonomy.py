from django.test import SimpleTestCase

from evaluations.taxonomy import FailureCategory, classify_failure, count_by_category


class ClassifyFailureTests(SimpleTestCase):
    def test_known_hard_constraint_check(self):
        self.assertEqual(
            classify_failure(
                check_name="hard_budget_respected", scenario_category="straightforward"
            ),
            FailureCategory.HARD_CONSTRAINT,
        )

    def test_known_grounding_check(self):
        self.assertEqual(
            classify_failure(check_name="winner_mentioned", scenario_category="straightforward"),
            FailureCategory.EXPLANATION_GROUNDING,
        )

    def test_intent_field_prefix(self):
        self.assertEqual(
            classify_failure(check_name="intent_field:month", scenario_category="straightforward"),
            FailureCategory.INTENT_EXTRACTION,
        )

    def test_robustness_category_falls_back_to_robustness(self):
        self.assertEqual(
            classify_failure(check_name="some_unknown_check", scenario_category="robustness"),
            FailureCategory.ROBUSTNESS,
        )

    def test_unknown_check_and_category_falls_back_to_unknown(self):
        self.assertEqual(
            classify_failure(check_name="totally_unmapped", scenario_category="straightforward"),
            FailureCategory.UNKNOWN,
        )

    def test_flow_mismatch_is_intent_extraction(self):
        self.assertEqual(
            classify_failure(check_name="flow_mismatch", scenario_category="robustness"),
            FailureCategory.INTENT_EXTRACTION,
        )

    def test_dependency_failure_check_maps_to_dependency_failure_category(self):
        # Cycle 1.5: a missing weather fixture (or a live provider
        # timeout/429/5xx, in --live-weather mode) must never be counted
        # as a SCORING/HARD_CONSTRAINT/etc product-quality failure - this
        # is exactly the mapping evaluations.runner's ScenarioResult
        # relies on via failed_check_names() == ["dependency_failure"].
        self.assertEqual(
            classify_failure(check_name="dependency_failure", scenario_category="straightforward"),
            FailureCategory.DEPENDENCY_FAILURE,
        )


class CountByCategoryTests(SimpleTestCase):
    def test_counts_grouped_correctly(self):
        pairs = [
            ("hard_budget_respected", "straightforward"),
            ("hard_budget_respected", "adversarial"),
            ("winner_mentioned", "straightforward"),
        ]
        counts = count_by_category(pairs)
        self.assertEqual(counts[FailureCategory.HARD_CONSTRAINT.value], 2)
        self.assertEqual(counts[FailureCategory.EXPLANATION_GROUNDING.value], 1)

    def test_empty_input_yields_empty_counts(self):
        self.assertEqual(count_by_category([]), {})
