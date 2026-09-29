from django.test import TestCase

from evaluations.conversation_invariants import (
    build_actual_state,
    check_exclusion_persistence,
    check_reference_resolved,
    classify_checkpoint_mismatch,
    evaluate_checkpoint,
    resolve_reference,
)
from evaluations.conversation_scenarios import ConversationScenario, ConversationTurn
from travel.models import Destination


def _destination(slug, **kwargs):
    defaults = dict(
        name=slug,
        country="Testland",
        latitude=10.0,
        longitude=10.0,
        trip_type="beach",
        cost_of_living=2,
        best_season="x",
        worst_season="x",
        short_description="x",
        points_of_interest=[],
    )
    defaults.update(kwargs)
    return Destination.objects.create(slug=slug, **defaults)


class BuildActualStateTests(TestCase):
    def test_uses_raw_intent_fields_and_resolved_slugs(self):
        intent = {"month": 10, "trip_type": "beach", "country": "Japan"}
        state = build_actual_state(intent, excluded_slugs=["b-slug", "a-slug"])
        self.assertEqual(state["month"], 10)
        self.assertEqual(state["trip_type"], "beach")
        self.assertEqual(state["excluded_slugs"], ["a-slug", "b-slug"])  # sorted


class EvaluateCheckpointTests(TestCase):
    def test_only_asserted_fields_are_compared(self):
        result = evaluate_checkpoint(
            {"trip_type": "beach"}, {"trip_type": "beach", "month": 3}, turn_index=0
        )
        self.assertTrue(result.all_match)
        self.assertEqual(len(result.comparisons), 1)

    def test_mismatch_is_detected(self):
        result = evaluate_checkpoint({"trip_type": "beach"}, {"trip_type": "city"}, turn_index=0)
        self.assertFalse(result.all_match)


class ClassifyCheckpointMismatchTests(TestCase):
    def _scenario(self, turns):
        return ConversationScenario(id="X-1", split="dev", family="drift", turns=tuple(turns))

    def test_no_earlier_checkpoint_is_a_plain_mismatch(self):
        scenario = self._scenario(
            [
                ConversationTurn(message="a"),
                ConversationTurn(message="b", expected_state={"trip_type": "city"}),
            ]
        )
        label = classify_checkpoint_mismatch(
            scenario, field_name="trip_type", turn_index=1, actual_value=None
        )
        self.assertEqual(label, "checkpoint_state_mismatch")

    def test_stale_state_when_actual_matches_a_superseded_earlier_value(self):
        scenario = self._scenario(
            [
                ConversationTurn(message="a", expected_state={"trip_type": "beach"}),
                ConversationTurn(message="b", expected_state={"trip_type": None}),
                ConversationTurn(message="c", expected_state={"trip_type": None}),
            ]
        )
        label = classify_checkpoint_mismatch(
            scenario, field_name="trip_type", turn_index=2, actual_value="beach"
        )
        self.assertEqual(label, "stale_state")

    def test_lost_context_when_a_real_value_reverts_to_null_unsuperseded(self):
        scenario = self._scenario(
            [
                ConversationTurn(message="a", expected_state={"country": "Japan"}),
                ConversationTurn(message="b"),
                ConversationTurn(message="c", expected_state={"country": "Japan"}),
            ]
        )
        label = classify_checkpoint_mismatch(
            scenario, field_name="country", turn_index=2, actual_value=None
        )
        self.assertEqual(label, "lost_context")


class ExclusionPersistenceTests(TestCase):
    def test_a_dropped_exclusion_is_flagged(self):
        from evaluations.conversation_invariants import CheckpointResult
        from evaluations.intent_eval import FieldComparison

        scenario = ConversationScenario(
            id="X-1",
            split="dev",
            family="memory",
            turns=(
                ConversationTurn(message="a", expected_state={"excluded_slugs": ["roma-it"]}),
                ConversationTurn(message="b", expected_state={"excluded_slugs": ["roma-it"]}),
            ),
        )
        checkpoints = {
            0: CheckpointResult(
                0, (FieldComparison("excluded_slugs", ["roma-it"], ["roma-it"], True),)
            ),
            1: CheckpointResult(1, (FieldComparison("excluded_slugs", ["roma-it"], [], False),)),
        }
        violations = check_exclusion_persistence(scenario, checkpoints)
        self.assertEqual(violations, [(1, "roma-it")])

    def test_no_violation_when_exclusion_holds(self):
        from evaluations.conversation_invariants import CheckpointResult
        from evaluations.intent_eval import FieldComparison

        scenario = ConversationScenario(
            id="X-1",
            split="dev",
            family="memory",
            turns=(
                ConversationTurn(message="a", expected_state={"excluded_slugs": ["roma-it"]}),
                ConversationTurn(message="b", expected_state={"excluded_slugs": ["roma-it"]}),
            ),
        )
        checkpoints = {
            0: CheckpointResult(
                0, (FieldComparison("excluded_slugs", ["roma-it"], ["roma-it"], True),)
            ),
            1: CheckpointResult(
                1, (FieldComparison("excluded_slugs", ["roma-it"], ["roma-it"], True),)
            ),
        }
        self.assertEqual(check_exclusion_persistence(scenario, checkpoints), [])


class ReferenceResolutionTests(TestCase):
    def test_resolve_reference_picks_the_right_ordinal(self):
        self.assertEqual(resolve_reference(referenced_scored_slugs=["a", "b", "c"], ordinal=2), "b")

    def test_resolve_reference_out_of_range_returns_none(self):
        self.assertIsNone(resolve_reference(referenced_scored_slugs=["a"], ordinal=3))

    def test_check_reference_resolved_true_when_reply_names_the_destination(self):
        destination = _destination("brasov-ro", name="Brasov", country="Romania")
        self.assertTrue(
            check_reference_resolved(reply="Brasov is a lovely choice.", destination=destination)
        )

    def test_check_reference_resolved_false_when_reply_never_mentions_it(self):
        destination = _destination("brasov-ro", name="Brasov", country="Romania")
        self.assertFalse(
            check_reference_resolved(
                reply="Here's something about Paris instead.", destination=destination
            )
        )
