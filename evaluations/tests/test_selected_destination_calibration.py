"""The calibration set is frozen, honest about its examples, and measured the
way production extracts - all checkable without a model. What the model
actually does with it can only be seen by running the command with real
credit."""

import hashlib
import json
import re
from collections import Counter

from django.test import SimpleTestCase, TestCase

from ai.orchestration import (
    INTENT_EXTRACTION_SYSTEM_PROMPT,
    INTENT_SCHEMA,
    NEAR_TERM_PLAN_PROMPT,
    SELECTED_DESTINATION_PROMPT,
)
from ai.provider import AIProviderError
from ai.tests.helpers import FixedClimateProvider, ScriptedProvider, intent, make_destination
from evaluations.selected_destination_calibration import (
    CASES,
    LOST_BY_MODEL,
    LOST_BY_VALIDATION,
    LOST_NOT_RECOMMENDATION,
    PROBE_CONVERSATIONS,
    format_probes,
    format_report,
    run_calibration,
    run_probes,
)

FROZEN_COUNTS = {
    "original_choice": 18,
    "original_control": 15,
    "want_to_go": 5,
    "go_to": 5,
    "stay_days": 4,
    "planning": 5,
    "thinking_of_going": 5,
    "with_date": 5,
    "other_languages": 5,
    "future_aspiration": 5,
    "comparison_question": 5,
    "incidental": 5,
    "region_discovery": 5,
    "region_choice": 3,
    "with_history": 6,
    "bare_after_options": 3,
    "bare_no_context": 3,
}
FROZEN_SHA256 = "60608b5981a4adbdcc19c62bc326805be27d0418e2b8c742f477028b97b8b4a0"


def _fingerprint(cases) -> str:
    rows = [
        [
            c.id,
            c.category,
            c.message,
            c.expect_select,
            c.expect_type,
            [list(h) for h in c.history],
            c.place,
        ]
        for c in cases
    ]
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class FrozenSetTests(SimpleTestCase):
    def test_the_set_is_the_set_that_was_measured(self):
        # Editing a case makes old and new numbers incomparable. Add a new
        # category instead; if the set really must change, update both
        # constants here on purpose.
        self.assertEqual(dict(Counter(c.category for c in CASES)), FROZEN_COUNTS)
        self.assertEqual(_fingerprint(CASES), FROZEN_SHA256)

    def test_it_contains_the_first_measurements_cases(self):
        self.assertEqual(sum(c.category == "original_choice" for c in CASES), 18)
        self.assertEqual(sum(c.category == "original_control" for c in CASES), 15)
        self.assertEqual(len(CASES), 102)

    def test_cases_are_unique(self):
        self.assertEqual(len({c.id for c in CASES}), len(CASES))
        self.assertEqual(len({(c.message, c.history) for c in CASES}), len(CASES))

    def test_every_pattern_the_calibration_is_about_is_covered(self):
        message_of = lambda category: [c.message.lower() for c in CASES if c.category == category]  # noqa: E731

        self.assertTrue(any(m.startswith("quero ir para ") for m in message_of("want_to_go")))
        self.assertTrue(any(m.startswith("vou para ") for m in message_of("go_to")))
        self.assertTrue(all("dias" in m or "semana" in m for m in message_of("stay_days")))
        self.assertTrue(any("planejando viajar" in m for m in message_of("planning")))
        self.assertTrue(any("pensando em ir" in m for m in message_of("thinking_of_going")))
        self.assertTrue(any("um dia" in m for m in message_of("future_aspiration")))

    def test_non_choices_and_future_aspirations_assert_what_they_should(self):
        for case in CASES:
            if case.category == "future_aspiration":
                self.assertIs(case.expect_select, False)
                self.assertEqual(case.expect_type, "future_intent")
            if case.category in {
                "comparison_question",
                "incidental",
                "region_discovery",
                "bare_no_context",
            }:
                self.assertIs(case.expect_select, False)
            if case.category.endswith("choice") or case.category in {
                "want_to_go",
                "go_to",
                "stay_days",
                "planning",
                "thinking_of_going",
                "with_date",
                "other_languages",
            }:
                self.assertIs(case.expect_select, True)
                self.assertEqual(case.expect_type, "recommendation")


class ProductDecisionTests(SimpleTestCase):
    """The two decisions revision 2 of the set encodes."""

    def case(self, message, *, history=False):
        return next(c for c in CASES if c.message == message and bool(c.history) == history)

    def test_a_region_the_traveler_chooses_is_a_selection_but_a_country_is_not(self):
        self.assertIs(self.case("quero ir pra Toscana").expect_select, True)
        self.assertIs(self.case("quero ir pra Itália").expect_select, False)
        self.assertIs(self.case("quero ir para a Itália em maio").expect_select, False)

    def test_a_bare_name_is_a_choice_only_among_the_options_just_presented(self):
        self.assertIs(self.case("Bali", history=True).expect_select, True)
        self.assertIs(self.case("Phuket", history=True).expect_select, True)
        # Not one of the options, and the same bare names with no options in sight:
        self.assertIs(self.case("Lisboa", history=True).expect_select, False)
        for message in ("Bali", "Lisboa", "Cusco"):
            self.assertIs(self.case(message).expect_select, False)


class PromptExamplesTests(SimpleTestCase):
    def test_the_calibrated_wording_never_uses_a_place_from_the_set(self):
        # An example the model can copy is an example it will pass: the
        # measurement would be measuring the prompt, not the field.
        wording = (SELECTED_DESTINATION_PROMPT + NEAR_TERM_PLAN_PROMPT).lower()
        for case in CASES:
            if case.place:
                self.assertIsNone(
                    re.search(rf"\b{re.escape(case.place.lower())}\b", wording), case.id
                )

    def test_the_paragraph_is_short_and_comes_last(self):
        # In the middle of the prompt, and longer, it made the model lose a
        # trip-type correction (see the comment on SELECTED_DESTINATION_PROMPT).
        self.assertLess(len(SELECTED_DESTINATION_PROMPT), 700)
        self.assertTrue(INTENT_EXTRACTION_SYSTEM_PROMPT.endswith(SELECTED_DESTINATION_PROMPT))
        self.assertEqual(INTENT_EXTRACTION_SYSTEM_PROMPT.count("selected_destination_name:"), 1)
        self.assertIn(NEAR_TERM_PLAN_PROMPT, INTENT_EXTRACTION_SYSTEM_PROMPT)

    def test_the_field_has_a_short_schema_description(self):
        description = INTENT_SCHEMA["schema"]["properties"]["selected_destination_name"][
            "description"
        ]
        self.assertLess(len(description), 300)

    def test_the_schema_stays_strict_and_requires_the_field(self):
        self.assertTrue(INTENT_SCHEMA["strict"])
        self.assertIn("selected_destination_name", INTENT_SCHEMA["schema"]["required"])


class _StubProvider:
    """Answers each case from a function of its message, and keeps what it was asked."""

    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def generate_structured_reply(self, messages, *, json_schema, temperature=None):
        self.calls.append((messages, json_schema, temperature))
        return self.answer(messages[-1].content)


def _raw(**fields):
    return {
        "message_type": "recommendation",
        "country": None,
        "selected_destination_name": None,
        **fields,
    }


class RunnerTests(TestCase):
    def test_it_asks_the_way_production_does(self):
        provider = _StubProvider(lambda message: _raw())

        run_calibration(provider, cases=CASES[:1])

        messages, schema, temperature = provider.calls[0]
        self.assertEqual(messages[0].role, "system")
        self.assertEqual(messages[0].content, INTENT_EXTRACTION_SYSTEM_PROMPT)
        self.assertEqual(messages[-1].content, CASES[0].message)
        self.assertEqual(schema["name"], INTENT_SCHEMA["name"])
        self.assertEqual(temperature, 0)

    def test_a_case_with_history_sends_it_before_the_message_with_replies_sanitized(self):
        case = next(c for c in CASES if c.category == "with_history")
        provider = _StubProvider(lambda message: _raw())

        run_calibration(provider, cases=[case])

        roles = [m.role for m in provider.calls[0][0]]
        self.assertEqual(roles, ["system", "user", "assistant", "user"])

    def test_it_tells_apart_where_a_missed_choice_was_lost(self):
        choice = lambda text: next(c for c in CASES if c.message == text)  # noqa: E731
        answers = {
            "quero ir pra Oslo": _raw(),  # the model left the field null
            "vou passar uns dias em Lisboa": _raw(
                message_type="future_intent", selected_destination_name="Lisbon"
            ),  # misclassified
            "quero ir pra Granada": _raw(selected_destination_name="Spain", country="Spain"),
        }
        provider = _StubProvider(lambda message: answers[message])

        report = run_calibration(provider, cases=[choice(m) for m in answers])

        reasons = {r.case.message: r.reason for r in report.results}
        self.assertEqual(reasons["quero ir pra Oslo"], LOST_BY_MODEL)
        self.assertEqual(reasons["vou passar uns dias em Lisboa"], LOST_NOT_RECOMMENDATION)
        self.assertEqual(reasons["quero ir pra Granada"], LOST_BY_VALIDATION)
        self.assertEqual(report.choices, (0, 3))

    def test_a_non_choice_that_gets_selected_fails_and_an_aspiration_must_stay_future_intent(self):
        controls = [
            c
            for c in CASES
            if c.message in {"o que você acha de Oslo?", "my dream is to visit Oslo one day"}
        ]
        provider = _StubProvider(
            lambda message: (
                _raw(selected_destination_name="Oslo")
                if "acha" in message
                else _raw(message_type="recommendation")
            )
        )

        report = run_calibration(provider, cases=controls)

        by_message = {r.case.message: r for r in report.results}
        self.assertFalse(by_message["o que você acha de Oslo?"].passed)
        self.assertIn("selected 'Oslo'", by_message["o que você acha de Oslo?"].reason)
        # Not selected, but classified as a recommendation instead of staying future_intent.
        self.assertIn("message_type", by_message["my dream is to visit Oslo one day"].reason)
        self.assertEqual(report.non_choices, (0, 2))

    def test_either_answer_is_fine_where_the_case_says_so(self):
        case = next(c for c in CASES if c.expect_select is None)

        for answer in (_raw(), _raw(selected_destination_name="Barcelona")):
            report = run_calibration(_StubProvider(lambda m, a=answer: a), cases=[case])
            self.assertTrue(report.results[0].passed)
        self.assertEqual(report.choices, (0, 0))

    def test_the_report_names_every_miss_with_both_the_raw_and_the_validated_answer(self):
        provider = _StubProvider(lambda message: _raw())

        text = format_report(run_calibration(provider, cases=CASES))

        self.assertIn("explicit-choice recall", text)
        self.assertIn("non-choice precision", text)
        self.assertIn("quero ir pra Oslo", text)
        self.assertIn(LOST_BY_MODEL, text)

    def test_a_provider_failure_is_not_swallowed_into_a_partial_measurement(self):
        def fail(message):
            raise AIProviderError("no credit")

        with self.assertRaises(AIProviderError):
            run_calibration(_StubProvider(fail), cases=CASES[:2])


class ProbeTests(TestCase):
    def setUp(self):
        make_destination("barcelona-es", name="Barcelona", country="Spain")
        make_destination("madrid-es", name="Madrid", country="Spain")

    def scripted(self, *intents):
        return ScriptedProvider(
            [{"intent": i, "climate_budget": {}, "state_clear": {}} for i in intents]
        )

    def test_each_conversation_is_fresh_and_reports_where_every_turn_went(self):
        provider = self.scripted(
            intent(country="Spain", selected_destination_name="Barcelona"),
            intent(country="Spain"),
        )

        results = run_probes(
            provider,
            conversations=(
                ("choice", ("quero ir pra Barcelona",)),
                ("discovery", ("quero uma cidade na Espanha",)),
            ),
            climate_provider=FixedClimateProvider(),
        )

        self.assertEqual(
            [(r.conversation, r.route, r.selected) for r in results],
            [("choice", "detail", "Barcelona"), ("discovery", "discovery", None)],
        )
        # The second conversation is fresh: it did not inherit the first one's choice.
        self.assertEqual(len(results[0].calls), 4)
        self.assertEqual(results[1].cards, ["Barcelona", "Madrid"])

    def test_the_turns_of_one_conversation_share_its_state(self):
        provider = self.scripted(
            intent(country="Spain", selected_destination_name="Barcelona"), intent(country="Spain")
        )

        results = run_probes(
            provider,
            conversations=(("sticks", ("quero ir pra Barcelona", "conte-me mais")),),
            climate_provider=FixedClimateProvider(),
        )

        self.assertEqual(
            [(r.turn, r.route, r.selected) for r in results],
            [(1, "detail", "Barcelona"), (2, "carried", "Barcelona")],
        )
        text = format_probes(results)
        self.assertIn("[sticks]", text)
        self.assertIn("2. 'conte-me mais'", text)

    def test_the_probe_list_covers_what_the_review_asked_for(self):
        names = {name for name, _ in PROBE_CONVERSATIONS}

        for expected in (
            "barcelona",
            "seville",
            "lisbon",
            "oslo",
            "granada",
            "valencia",
            "prague",
            "cusco",
            "thailand",
            "spain-city",
            "kyoto-aspiration",
            "continuity",
            "replacement",
            "incidental-mention",
            "bare-name-after-recommendations",
            "reopen",
        ):
            self.assertIn(expected, names)
