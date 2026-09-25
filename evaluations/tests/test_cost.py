from django.test import SimpleTestCase

from evaluations.cost import CostTracker


class CostTrackerTests(SimpleTestCase):
    def test_starts_at_zero(self):
        tracker = CostTracker(model_name="gpt-4o-mini")
        self.assertEqual(tracker.pipeline_scenarios, 0)
        self.assertEqual(tracker.estimated_usd, 0.0)

    def test_pipeline_call_increments_scenario_count(self):
        tracker = CostTracker(model_name="gpt-4o-mini")
        tracker.record_pipeline_call(scenario_message="hi", reply="hello there")
        self.assertEqual(tracker.pipeline_scenarios, 1)
        self.assertGreater(tracker.estimated_usd, 0.0)

    def test_judge_call_increments_judge_count(self):
        tracker = CostTracker(model_name="gpt-4o-mini")
        tracker.record_judge_call(scenario_message="hi", reply="hello there")
        self.assertEqual(tracker.judge_calls, 1)

    def test_more_calls_cost_more(self):
        tracker = CostTracker(model_name="gpt-4o-mini")
        tracker.record_pipeline_call(scenario_message="hi", reply="hello")
        cost_after_one = tracker.estimated_usd
        tracker.record_pipeline_call(scenario_message="hi", reply="hello")
        self.assertGreater(tracker.estimated_usd, cost_after_one)

    def test_to_json_includes_the_disclaimer_note(self):
        tracker = CostTracker(model_name="gpt-4o-mini")
        payload = tracker.to_json()
        self.assertIn("estimate", payload["note"].lower())
        self.assertEqual(payload["model_name"], "gpt-4o-mini")
