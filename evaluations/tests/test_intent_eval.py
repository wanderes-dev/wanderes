from django.test import SimpleTestCase

from evaluations.intent_eval import aggregate_field_accuracy, evaluate_intent
from evaluations.scenarios import Scenario


def _scenario(expected_intent):
    return Scenario(
        id="T-1",
        split="dev",
        category="straightforward",
        message="test",
        expected_intent=expected_intent,
    )


class EvaluateIntentTests(SimpleTestCase):
    def test_only_declared_fields_are_compared(self):
        scenario = _scenario({"month": 7})
        result = evaluate_intent(scenario, {"month": 7, "trip_type": "beach"})
        self.assertEqual(len(result.comparisons), 1)
        self.assertTrue(result.all_match)

    def test_mismatch_is_detected(self):
        scenario = _scenario({"month": 7})
        result = evaluate_intent(scenario, {"month": 8})
        self.assertFalse(result.all_match)
        self.assertEqual(result.accuracy, 0.0)

    def test_missing_actual_field_counts_as_mismatch_unless_both_none(self):
        scenario = _scenario({"trip_type": "beach"})
        result = evaluate_intent(scenario, {})
        self.assertFalse(result.all_match)

    def test_expected_none_matches_missing_actual(self):
        scenario = _scenario({"country": None})
        result = evaluate_intent(scenario, {})
        self.assertTrue(result.all_match)

    def test_list_fields_compare_as_sets(self):
        scenario = _scenario({"excluded_place_names": ["Rome", "Prague"]})
        result = evaluate_intent(scenario, {"excluded_place_names": ["Prague", "Rome"]})
        self.assertTrue(result.all_match)

    def test_float_fields_compare_with_tolerance(self):
        scenario = _scenario({"min_temp_c": 22.0})
        result = evaluate_intent(scenario, {"min_temp_c": 22.0000001})
        self.assertTrue(result.all_match)

    def test_empty_expected_intent_is_trivially_all_match(self):
        scenario = _scenario({})
        result = evaluate_intent(scenario, {"month": 7})
        self.assertTrue(result.all_match)
        self.assertEqual(result.accuracy, 1.0)

    def test_accuracy_is_fraction_matching(self):
        scenario = _scenario({"month": 7, "trip_type": "beach"})
        result = evaluate_intent(scenario, {"month": 7, "trip_type": "city"})
        self.assertEqual(result.accuracy, 0.5)


class AggregateFieldAccuracyTests(SimpleTestCase):
    def test_aggregates_per_field_across_scenarios(self):
        r1 = evaluate_intent(_scenario({"month": 7}), {"month": 7})
        r2 = evaluate_intent(_scenario({"month": 7}), {"month": 8})
        accuracy = aggregate_field_accuracy([r1, r2])
        self.assertEqual(accuracy["month"], 0.5)

    def test_field_only_checked_by_some_scenarios_only_counts_those(self):
        r1 = evaluate_intent(_scenario({"month": 7}), {"month": 7})
        r2 = evaluate_intent(_scenario({"trip_type": "beach"}), {"trip_type": "beach"})
        accuracy = aggregate_field_accuracy([r1, r2])
        self.assertEqual(accuracy["month"], 1.0)
        self.assertEqual(accuracy["trip_type"], 1.0)

    def test_empty_results_list_yields_empty_dict(self):
        self.assertEqual(aggregate_field_accuracy([]), {})
