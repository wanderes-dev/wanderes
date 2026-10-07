"""The relevance scenarios' own checks and runner, without a model: what they
measure, how a step fails, and that the set covers what was asked for."""

from django.test import SimpleTestCase, TestCase

from ai.tests.helpers import FixedClimateProvider, ScriptedProvider, intent, make_destination
from evaluations.relevance_scenarios import (
    CHECKS,
    SCENARIOS,
    Scenario,
    Step,
    check_step,
    format_report,
    measure,
    run_relevance,
)


class MeasureTests(SimpleTestCase):
    def test_it_counts_the_content_the_investigation_found_being_pushed(self):
        reply = (
            "Visite a Sagrada Família e o Parque Güell. Com 22°C o clima é ótimo - "
            "quer ver um vídeo da Espanha?"
        )

        m = measure(reply)

        self.assertEqual(m["attractions"], 2)
        self.assertGreaterEqual(m["climate"], 2)
        self.assertEqual(m["video"], 1)
        self.assertTrue(m["closing_question"])

    def test_it_spots_invented_price_figures_in_either_notation(self):
        for text in ("Um hotel custa €80 por noite.", "Cerca de 120 euros por dia.", "Uns $90."):
            with self.subTest(text=text):
                self.assertTrue(measure(text)["price_figures"])
        self.assertFalse(
            measure("Não tenho preços verificados, só o nível de custo.")["price_figures"]
        )

    def test_it_spots_a_claimed_fix_but_not_an_acknowledgement(self):
        self.assertTrue(measure("Já ajustei as datas da busca para dia 5.")["fix_claim"])
        self.assertTrue(measure("I updated the link with your dates.")["fix_claim"])
        self.assertTrue(measure("A data foi corrigida na busca.")["fix_claim"])
        self.assertFalse(measure("Entendi: você quer ir no dia 5 e ficar 3 dias.")["fix_claim"])

    def test_saying_it_cannot_change_something_is_not_a_claimed_fix(self):
        for text in (
            "Infelizmente, não posso corrigir ou ajustar as datas diretamente.",
            "Você precisaria corrigir isso na plataforma e ajustar a data para o dia 5.",
            "I can't change the dates on that site; you'll need to update them there.",
        ):
            with self.subTest(text=text):
                self.assertFalse(measure(text)["fix_claim"])

    def test_it_spots_a_plain_statement_of_what_it_cannot_do(self):
        self.assertTrue(measure("Não consigo alterar as datas na busca, ainda.")["limits"])
        self.assertTrue(measure("I can't change the dates on that site.")["limits"])
        self.assertFalse(measure("Claro, vamos falar de Barcelona.")["limits"])


class CheckStepTests(SimpleTestCase):
    def measures(self, **over):
        base = {
            "chars": 200,
            "attractions": 0,
            "climate": 0,
            "video": 0,
            "price_figures": 0,
            "fix_claim": False,
            "closing_question": False,
            "limits": False,
        }
        return {**base, **over}

    def test_a_clean_step_has_no_failures(self):
        step = Step("x", expect_card=False, forbid=CHECKS, max_chars=300)

        self.assertEqual(check_step(step, card=False, measures=self.measures()), [])

    def test_every_expectation_can_fail(self):
        step = Step(
            "x",
            expect_card=False,
            forbid=("attractions", "video"),
            require=("limits",),
            max_chars=100,
        )

        failures = check_step(
            step, card=True, measures=self.measures(attractions=3, video=1, chars=500)
        )

        text = " | ".join(failures)
        for expected in (
            "card present",
            "forbidden attractions",
            "forbidden video",
            "can't set",
            "too long",
        ):
            self.assertIn(expected, text)

    def test_rich_means_a_real_destination_answer(self):
        step = Step("x", require=("rich",))

        self.assertTrue(check_step(step, card=False, measures=self.measures(chars=300)))
        self.assertFalse(check_step(step, card=False, measures=self.measures(attractions=2)))
        self.assertFalse(check_step(step, card=False, measures=self.measures(chars=900)))


class ScenarioSetTests(SimpleTestCase):
    def test_the_set_covers_the_requested_situations(self):
        ids = {s.id for s in SCENARIOS}

        self.assertEqual(
            ids,
            {
                "challenge",
                "repeated-complaint",
                "cost",
                "activities",
                "tell-me-more",
                "stays",
                "date-correction",
                "thanks",
                "ordinary-follow-ups",
                "broad-exploratory",
            },
        )

    def test_every_scenario_opens_with_a_fresh_choice_that_must_stay_rich_with_its_card(self):
        for scenario in SCENARIOS:
            first = scenario.steps[0]
            self.assertEqual(first.message, "quero ir pra Barcelona", scenario.id)
            self.assertTrue(first.expect_card, scenario.id)
            self.assertIn("rich", first.require, scenario.id)

    def test_the_complaints_may_not_claim_a_fix_or_recite_the_place(self):
        by_id = {s.id: s for s in SCENARIOS}

        for scenario_id in ("challenge", "repeated-complaint"):
            last = by_id[scenario_id].steps[-1]
            self.assertIn("attractions", last.forbid)
            self.assertIn("fix_claim", last.forbid)
            # Wanderes does carry dates and travelers now, so what it must not do
            # is claim a change it didn't make - not insist it can't make one.
            self.assertNotIn("limits", last.require)

    def test_ordinary_follow_ups_may_not_recite_the_place(self):
        steps = next(s for s in SCENARIOS if s.id == "ordinary-follow-ups").steps[1:]

        self.assertEqual(len(steps), 3)
        for step in steps:
            self.assertTrue({"attractions", "climate", "video"} <= set(step.forbid))


class _RepliesProvider(ScriptedProvider):
    """Streams a scripted reply per turn."""

    def __init__(self, turns, replies):
        super().__init__(turns)
        self.replies = replies

    def stream_reply(self, messages, *, max_tokens=None, temperature=None):
        self.stream_calls += 1
        self.stream_messages.append(list(messages))
        yield self.replies[self.stream_calls - 1]


def _turns(*selections):
    return [
        {
            "intent": intent(country="Spain", continent="europe", selected_destination_name=name),
            "climate_budget": {},
            "state_clear": {},
        }
        for name in selections
    ]


class RunnerTests(TestCase):
    def setUp(self):
        make_destination("barcelona-es", name="Barcelona", country="Spain", trip_type="culture")
        self.scenario = Scenario(
            "cost",
            "quanto custa?",
            (
                Step("quero ir pra Barcelona", expect_card=True, require=("rich",)),
                Step("quanto custa?", expect_card=False, forbid=("attractions", "price_figures")),
            ),
        )

    def run_with(self, replies):
        provider = _RepliesProvider(_turns("Barcelona", None), replies)
        return run_relevance(
            provider, scenarios=[self.scenario], climate_provider=FixedClimateProvider()
        )

    def test_a_relevant_reply_passes_every_step_and_the_routes_are_reported(self):
        results = self.run_with(
            [
                "Visite a Sagrada Família, o Parque Güell e a Rambla - " + "x" * 400,
                "Só tenho o nível de custo, não preços verificados.",
            ]
        )

        self.assertEqual([r.failures for r in results], [[], []])
        self.assertEqual([r.route for r in results], ["detail", "carried"])
        self.assertEqual([r.card for r in results], [True, False])

    def test_a_reply_that_recites_the_place_and_invents_prices_fails_the_follow_up(self):
        results = self.run_with(
            [
                "Visite a Sagrada Família, o Parque Güell e a Rambla - " + "x" * 400,
                "Uma diária custa €120. Não perca a Sagrada Família!",
            ]
        )

        self.assertEqual(results[0].failures, [])
        text = " ".join(results[1].failures)
        self.assertIn("forbidden attractions", text)
        self.assertIn("forbidden price_figures", text)

    def test_the_report_lists_failures_and_the_footprint_of_the_later_turns(self):
        results = self.run_with(
            [
                "Sagrada Família, Park Güell, La Rambla " + "x" * 500,
                "Veja a Sagrada Família e a Rambla!",
            ]
        )

        report = format_report(results)

        self.assertIn("[cost]", report)
        self.assertIn("FAIL", report)
        self.assertIn("later turns with landmarks: 1/1", report)
        self.assertIn("fresh choice kept rich with its card: 1/1", report)
