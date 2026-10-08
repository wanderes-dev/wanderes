"""The frozen trip-details set's own machinery, without a model."""

from django.test import SimpleTestCase

from ai.trip_details import validate_components
from evaluations.trip_details_set import (
    ANY,
    PHRASES,
    differences,
    expected_components,
    format_report,
    run_trip_details_set,
)


class _EchoProvider:
    """Answers each phrase with exactly what it says it states."""

    def __init__(self, phrases):
        self.by_message = {p.message: p for p in phrases}

    def generate_structured_reply(
        self, messages, *, json_schema, max_tokens=None, temperature=None
    ):
        content = messages[-1].content
        message = content.rsplit("The traveler's latest message:\n", 1)[-1]
        wanted = expected_components(self.by_message[message].expect)
        for key in ("start", "end"):
            wanted[key] = {k: (None if v == ANY else v) for k, v in wanted[key].items()}
        return wanted


class FrozenSetTests(SimpleTestCase):
    def test_it_stays_a_small_frozen_set(self):
        self.assertEqual(len(PHRASES), 39)
        self.assertEqual(len({p.id for p in PHRASES}), 39)
        self.assertEqual(len({p.message for p in PHRASES}), 39)

    def test_it_covers_the_shapes_the_feature_depends_on(self):
        ids = {p.id for p in PHRASES}

        for needed in (
            "bare-day",
            "day-05-and-days",
            "this-month",
            "next-month",
            "range",
            "regression-this-month-nights",
            "days-alone",
            "adults-and-a-child",
            "child-with-age",
            "age-reply",
            "forget-the-start",
            "complaint-about-an-earlier-reply",
            "a-past-trip",
            "rooms-please",
            "rooms-search",
            "rooms-forgotten",
        ):
            self.assertIn(needed, ids)

    def test_a_phrase_that_states_nothing_expects_everything_blank(self):
        silent = [p for p in PHRASES if not p.expect]

        self.assertGreaterEqual(len(silent), 4)
        for phrase in silent:
            wanted = expected_components(phrase.expect)
            self.assertIsNone(wanted["adults"])
            self.assertEqual(wanted["child_ages"], [])
            self.assertEqual(wanted["cleared_fields"], [])

    def test_a_phrase_that_needs_the_question_is_short_enough_to_be_given_it(self):
        from ai.trip_details import previous_question_for_extraction

        for phrase in (p for p in PHRASES if p.question):
            history = [{"role": "assistant", "content": phrase.question}]
            self.assertIsNotNone(
                previous_question_for_extraction(history, phrase.message), phrase.id
            )

    def test_differences_reports_what_is_off_and_ignores_what_is_not_pinned(self):
        expect = {"start": {"day": 5, "month": ANY}, "adults": 2}
        good = validate_components({"start": {"day": 5, "month": 11}, "adults": 2})
        bad = validate_components(
            {
                "start": {"day": 5, "month": 11},
                "adults": 3,
                "children": 1,
                "cleared_fields": ["stay"],
            }
        )

        self.assertEqual(differences(good, expect), [])
        text = " | ".join(differences(bad, expect))
        self.assertIn("adults: wanted 2, got 3", text)
        self.assertIn("children: wanted None, got 1", text)
        self.assertIn("cleared_fields", text)

    def test_the_runner_passes_a_model_that_reports_exactly_what_each_phrase_states(self):
        results = run_trip_details_set(_EchoProvider(PHRASES))

        self.assertTrue(
            all(r.passed for r in results), [r.phrase.id for r in results if not r.passed]
        )
        self.assertIn("phrases matching: 39/39", format_report(results))
