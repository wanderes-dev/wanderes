"""The last correction pass, each defect pinned at the unit that decides it and through
whole turns with the model's side scripted: a Spanish month said alone, the price note
and hotel price ranges, one child's age corrected against a full set of ages, and a niece
or nephew joining the party.

The model's answers are scripted here, shaped the way the real one answered when these
went wrong (the age alone for a correction, one adult for a message about a niece); what
is under test is everything the application does with them."""

import re

from django.test import SimpleTestCase

from ai import memory
from ai.orchestration import _PRICE_NOTES, _chat_language, _price_note, _price_verdict
from ai.tests.helpers import ScriptedProvider
from ai.tests.test_selected_destination import WHEN, spain, turn
from ai.tests.test_trip_details import TODAY, comps, record
from ai.tests.test_trip_details_flow import _TripCase, plain, query_of
from ai.trip_details import (
    TRIP_DETAILS_SYSTEM_PROMPT,
    apply_components,
    guard_components,
    has_trip_detail_cues,
    resolve,
    restrict_clears,
)
from users.models import User

SPANISH_MONTHS = {
    1: ("enero", "ene"),
    2: ("febrero", "feb"),
    3: ("marzo",),
    4: ("abril", "abr"),
    5: ("mayo",),
    6: ("junio", "jun"),
    7: ("julio", "jul"),
    8: ("agosto", "ago"),
    9: ("septiembre", "setiembre", "sep", "sept"),
    10: ("octubre", "oct"),
    11: ("noviembre", "nov"),
    12: ("diciembre", "dic"),
}


def stays_turn(**trip):
    """A turn that chooses Barcelona and carries trip components."""
    return turn(
        spain(
            is_accommodation_request=True,
            accommodation_place_name="Barcelona",
            selected_destination_name="Barcelona",
        ),
        trip_details=trip,
    )


# --- 1. Spanish months said alone -----------------------------------------------


class SpanishMonthGateTests(SimpleTestCase):
    def test_every_spanish_month_name_and_its_variants_is_worth_a_trip_details_call(self):
        for month, names in SPANISH_MONTHS.items():
            for name in names:
                for form in (name, name.capitalize(), name.upper(), f"{name}."):
                    with self.subTest(month=month, form=form):
                        self.assertTrue(has_trip_detail_cues(f"Quiero ir a Lisboa en {form}"))

    def test_months_inside_ordinary_sentences_open_it_too(self):
        for message in (
            "Me gustaría viajar a mediados de enero",
            "Pensamos ir a finales de septiembre",
            "Quizás en Semana Santa, a principios de abril",
            "para setiembre, si se puede",
            "Vamos en dic.",
        ):
            with self.subTest(message=message):
                self.assertTrue(has_trip_detail_cues(message))

    def test_spanish_that_says_nothing_about_the_trip_still_costs_no_call(self):
        for message in (
            "Quiero ir a la playa",
            "Quiero ir al mar",
            "¿Qué se come allí?",
            "gracias",
            "Me encanta el mar",
        ):
            with self.subTest(message=message):
                self.assertFalse(has_trip_detail_cues(message))

    def test_the_months_that_already_worked_still_do(self):
        for message in ("Quero ir em janeiro", "I want to go in March", "Je pars en juin"):
            with self.subTest(message=message):
                self.assertTrue(has_trip_detail_cues(message))


class SpanishMonthStateTests(SimpleTestCase):
    def test_each_month_said_alone_waits_for_its_day_and_the_days_complete_it(self):
        for month in SPANISH_MONTHS:
            with self.subTest(month=month):
                said = apply_components(None, comps(month=month), TODAY)

                self.assertIsNone(said.record["start_date"])
                self.assertEqual(said.record["start_month"], month)

                later = apply_components(said.record, comps(day=20, end_day=24), TODAY)

                year = 2026 if month >= 10 else 2027  # the next time that month comes round
                self.assertEqual(later.record["start_date"], f"{year}-{month:02d}-20")
                self.assertEqual(later.record["stay_length"], 4)
                self.assertNotIn("start_month", later.record)


class SpanishMonthWholeTurnTests(_TripCase):
    def new_conversation(self, name):
        self.user = User.objects.create_user(email=f"{name}@example.com", password="x")
        self.key = memory.conversation_key(user=self.user, session_key=None)
        memory.clear_history(self.key)

    def test_diciembre_said_alone_then_del_20_al_24_is_december(self):
        provider = ScriptedProvider(
            [
                turn(
                    spain(selected_destination_name="Barcelona"),
                    trip_details={"start": {"month": 12}},
                ),
                plain(start={"day": 20}, end={"day": 24}, adults=3),
            ]
        )

        self.say(provider, "Quiero ir a Barcelona en diciembre")

        self.assertEqual(self.trip_calls(provider), 1)  # the gate let the message through
        self.assertEqual(self.stored()["start_month"], 12)
        self.assertIsNone(self.stored()["start_date"])

        result, _, _ = self.say(provider, "del 20 al 24, somos 3")

        self.assertEqual(self.stored()["start_date"], "2026-12-20")
        url = dict(query_of(self.url_of(result)))
        self.assertEqual(
            (url["checkin"], url["checkout"], url["group_adults"]),
            ("2026-12-20", "2026-12-24", "3"),
        )

    def test_the_gate_opens_for_every_spanish_month_in_a_whole_turn(self):
        for month, names in SPANISH_MONTHS.items():
            with self.subTest(month=month):
                self.new_conversation(f"month{month}")
                provider = ScriptedProvider(
                    [
                        turn(
                            spain(selected_destination_name="Barcelona"),
                            trip_details={"start": {"month": month}},
                        ),
                        plain(start={"day": 20}, end={"day": 24}),
                    ]
                )

                self.say(provider, f"Quiero ir a Barcelona en {names[0]}")
                self.assertEqual(self.trip_calls(provider), 1)
                self.assertEqual(self.stored()["start_month"], month)

                self.say(provider, "del 20 al 24")
                year = 2026 if month >= 10 else 2027
                self.assertEqual(self.stored()["start_date"], f"{year}-{month:02d}-20")


# --- 2. prices -------------------------------------------------------------------------


class HotelPriceRangeTests(SimpleTestCase):
    def verdict(self, sentence, given=()):
        return _price_verdict(sentence, set(given))

    def test_a_hotel_price_is_specific_even_with_the_word_budget_in_the_sentence(self):
        for sentence in (
            "A good budget hotel price in Lisbon typically ranges from around €50 to €100 per "
            "night.",
            "In Lisbon, budget hotel prices can generally range from around €50 to €100 per "
            "night, depending on the location and the amenities offered.",
            "Budget hotels in Lisbon start around €60.",
            "Hotels in Lisbon cost €100/night.",
            "A budget hostel bed is roughly 25 euros.",
            "Um hotel econômico em Lisboa custa cerca de 50 a 100 euros por noite.",
            "Un hotel barato en Lisboa cuesta unos 50 a 100 euros por noche.",
            "Regarding a taxi from the airport, the cost can vary but generally it should be "
            "between €15 to €25, depending on traffic.",
            "Generalmente, se puede encontrar un menú en un restaurante local por unos 12 a 25 "
            "euros.",
        ):
            with self.subTest(sentence=sentence):
                self.assertEqual(self.verdict(sentence), "specific")

    def test_a_general_trip_budget_that_calls_itself_an_estimate_is_still_kept(self):
        for sentence in (
            "For a week in Lisbon, plan a budget of about €1,200 per person, covering hotel, "
            "food and activities.",
            "Um orçamento aproximado de 1.500 euros para a semana, incluindo hotel e comida.",
            "Para el viaje, calcula unos 900 euros de presupuesto, con alojamiento y comidas.",
            "A week in Lisbon can cost around 1,200 euros per person.",
            "Budget about €80 per day for food and activities, as a rough guide.",
        ):
            with self.subTest(sentence=sentence):
                self.assertEqual(self.verdict(sentence), "labeled")

    def test_a_week_or_a_trip_in_the_sentence_does_not_turn_the_price_of_a_thing_into_a_budget(
        self,
    ):
        for sentence in (
            "A week in a Lisbon hotel costs about €700.",
            "Uma semana de hotel em Lisboa custa cerca de 700 euros.",
            "Una semana de hotel en Lisboa cuesta unos 700 euros.",
            "A flight for the trip costs around €300.",
            "A passagem da viagem sai por volta de 1.500 reais.",
        ):
            with self.subTest(sentence=sentence):
                self.assertEqual(self.verdict(sentence), "specific")

    def test_a_nightly_figure_is_a_hotels_rate_even_inside_a_budget_sentence(self):
        for sentence in (
            "For your trip, plan a budget of around €150 per night.",
            "Calcule um orçamento de cerca de 150 euros por noite.",
            "Presupuesta unos 150 euros por noche para el viaje.",
        ):
            with self.subTest(sentence=sentence):
                self.assertEqual(self.verdict(sentence), "specific")

    def test_the_travelers_own_figures_are_theirs_to_hear_again(self):
        self.assertIsNone(self.verdict("Under $100 a night, then: hotels at 100 or less.", {"100"}))
        self.assertIsNone(self.verdict("Com os seus 2000 euros dá para a semana.", {"2000"}))

    def test_a_figure_the_traveler_gave_does_not_make_a_derived_hotel_rate_theirs(self):
        sentence = "Com 2000 euros dá para um hotel de 100 euros por noite."

        self.assertEqual(self.verdict(sentence, {"2000"}), "specific")


class PriceNoteTests(SimpleTestCase):
    def test_no_note_holds_a_figure_or_a_currency(self):
        for language, notes in _PRICE_NOTES.items():
            for kind, text in notes.items():
                with self.subTest(language=language, kind=kind):
                    self.assertIsNone(_price_verdict(text, set()))
                    self.assertFalse(re.search(r"[\d$€£]", text))

    def test_the_note_is_in_the_language_the_traveler_writes(self):
        for message, earlier, language in (
            ("e um jantar num restaurante bom?", [], "pt"),
            ("quanto custa em média um hotel por noite lá?", [], "pt"),
            ("e quanto custa um jantar? tá, valeu", [], "pt"),
            ("¿y un menú del día en Roma?", [], "es"),
            ("tengo 1800 euros para una semana, ¿a dónde puedo ir?", [], "es"),
            ("and a taxi from the airport?", [], "en"),
            ("What's a good budget hotel price in Lisbon per night?", [], "en"),
            ("ok", ["¿cuánto cuesta un vuelo a Roma?"], "es"),  # a bare reply: the one before it
            ("Roma?", ["quanto custa um jantar lá?"], "pt"),
            ("Madrid del 3 al 6 de diciembre, 2 adultos", [], "es"),  # a month name
            ("Lisboa de 3 a 7 de dezembro, somos dois", [], "pt"),
            ("Dec 5 for 4 nights, 2 adults", [], "en"),
            ("dos de ellos son niños", [], "es"),
            ("vale a pena alugar carro?", [], "pt"),
            # a bare reply: the replies before it are in the traveler's language
            ("sim", ["Claro! Posso ajudar com o hotel em Roma. Quando você vai?"], "pt"),
            ("vale", ["¡Claro! Puedo ayudarte con el hotel en Roma. ¿Cuándo vas?"], "es"),
            ("onde posso comer em Roma?", [], "pt"),
            ("preciso de um hotel perto do centro", [], "pt"),
            ("dónde puedo comer en Roma", [], "es"),
            ("necesito un hotel cerca del centro", [], "es"),
            ("where can I eat in Rome?", [], "en"),
            ("obrigado", [], "pt"),
            ("gracias", [], "es"),
            ("thanks", [], "en"),
            ("ok", [], "en"),  # nothing to go on
            ("Combien coûte un hôtel ?", [], "en"),  # a language without a note gets English
        ):
            with self.subTest(message=message):
                self.assertEqual(_chat_language(message, earlier), language)

    def test_the_note_holds_what_each_kind_has_to_say(self):
        dropped = _price_note("dropped", "e um jantar num restaurante bom?", [])
        rough = _price_note("rough", "¿cuánto debería presupuestar?", [])

        self.assertIn("não tem preços verificados", dropped)
        self.assertIn("estimaciones aproximadas", rough)


class PriceNoteWholeTurnTests(_TripCase):
    def conversation(self, reply_text, first):
        provider = ScriptedProvider(
            [turn(spain(selected_destination_name="Barcelona")), plain(), plain()],
            reply_text=reply_text,
        )
        self.say(provider, first)
        return provider

    def spoken(self, provider, message):
        self.say(provider, message)
        return memory.get_history(self.key)[-1]["content"]

    def test_the_note_is_the_applications_in_the_travelers_language_in_three_languages(self):
        for first, question, language, reply in (
            (
                "quero ir pra Barcelona",
                "e um jantar num restaurante bom?",
                "pt",
                "Barcelona é boa. Um jantar custa cerca de 40 euros por pessoa. Aproveite.",
            ),
            (
                "quiero ir a Barcelona",
                "¿y un menú del día?",
                "es",
                "Barcelona es genial. Un menú del día cuesta unos 20 euros. Disfruta.",
            ),
            (
                "I want to go to Barcelona",
                "and a taxi from the airport?",
                "en",
                "Barcelona is great. A taxi costs between €30 and €40. Enjoy.",
            ),
        ):
            with self.subTest(language=language):
                self.user = User.objects.create_user(email=f"{language}@example.com", password="x")
                self.key = memory.conversation_key(user=self.user, session_key=None)
                memory.clear_history(self.key)
                provider = self.conversation(reply, first)

                spoken = self.spoken(provider, question)

                self.assertTrue(spoken.endswith(_PRICE_NOTES[language]["dropped"]))
                self.assertFalse(
                    re.search(r"\b(?:30|40|20)\b", spoken)
                )  # the invented figures are gone
                # nothing asked the model to write the note, so it could not answer the question
                self.assertEqual(provider.reply_calls, 0)

    def test_a_budget_that_does_not_call_itself_an_estimate_gets_the_rough_note_in_the_same_way(
        self,
    ):
        provider = self.conversation(
            "Uma semana custa 1.200 euros no total.", "quero ir pra Barcelona"
        )

        spoken = self.spoken(provider, "quanto devo levar?")

        self.assertIn("1.200 euros", spoken)
        self.assertTrue(spoken.endswith(_PRICE_NOTES["pt"]["rough"]))
        self.assertEqual(provider.reply_calls, 0)

    def test_a_hotel_range_with_the_word_budget_is_taken_out_and_not_passed_off_as_a_trip_budget(
        self,
    ):
        provider = self.conversation(
            "Lisbon is lovely. A good budget hotel price in Lisbon is around €50 to €100 per "
            "night. Enjoy it.",
            "I want to go to Barcelona",
        )

        spoken = self.spoken(provider, "What's a good budget hotel price per night?")

        self.assertNotIn("€", spoken.replace(_PRICE_NOTES["en"]["dropped"], ""))
        self.assertTrue(spoken.endswith(_PRICE_NOTES["en"]["dropped"]))

    def test_the_travelers_own_budget_is_repeated_without_any_note(self):
        provider = self.conversation(
            "Com os seus 2000 euros dá para uma semana.", "quero ir pra Barcelona"
        )

        spoken = self.spoken(provider, "tenho 2000 euros, dá?")

        self.assertEqual(spoken, "Com os seus 2000 euros dá para uma semana.")


# --- 3. one child's age corrected -----------------------------------------------------------


class AgeCorrectionPathTests(SimpleTestCase):
    """The model answered a correction with the age alone, which used to replace the other
    child's age. Both the guard (it knows the message) and the merge (it knows the record)
    now keep the ages of the children the correction says nothing about."""

    KIDS = record(adults=2, children=2, child_ages=[3, 8])

    def read(self, message, current=None, **parts):
        current = current or self.KIDS
        return apply_components(current, guard_components(comps(**parts), message, current), TODAY)

    def test_the_child_is_found_by_the_old_age_in_the_message(self):
        for message, current, ages, expected in (
            ("o de 8 na verdade tem 9", self.KIDS, [9], [3, 9]),
            (
                "el de 8 en realidad tiene 9",
                record(adults=2, children=2, child_ages=[6, 8]),
                [9],
                [6, 9],
            ),
            ("the 8 year old is actually 9", self.KIDS, [9], [3, 9]),
            ("la de 3 tiene 4", self.KIDS, [4], [4, 8]),
        ):
            with self.subTest(message=message):
                applied = self.read(message, current, ages=ages)

                self.assertEqual(applied.record["child_ages"], expected)
                self.assertEqual((applied.record["adults"], applied.record["children"]), (2, 2))
                self.assertEqual(applied.issues, ())

    def test_an_age_a_child_already_has_said_again_is_not_a_change_and_not_a_question(self):
        for message in ("tem 8 anos", "o de 8 tem 8", "she's 8"):
            with self.subTest(message=message):
                applied = self.read(message, ages=[8])

                self.assertEqual(applied.record["child_ages"], [3, 8])
                self.assertEqual(applied.issues, ())

    def test_a_correction_in_other_wordings_still_finds_its_child(self):
        for message, current, ages, expected in (
            ("na verdade a de 3 já fez 4", self.KIDS, [4], [4, 8]),
            ("correction: the 3 year old is 5", self.KIDS, [5], [5, 8]),
            ("perdón, el de 8 tiene 10", self.KIDS, [10], [3, 10]),
            (
                "o mais novo, que tem 5, na verdade tem 6",
                record(adults=2, children=3, child_ages=[5, 9, 12]),
                [6],
                [6, 9, 12],
            ),
        ):
            with self.subTest(message=message):
                applied = self.read(message, current, ages=ages)

                self.assertEqual(applied.record["child_ages"], expected)
                self.assertEqual(applied.issues, ())

    def test_the_same_when_the_model_also_reports_a_count(self):
        for count in (1, 2):
            with self.subTest(count=count):
                applied = self.read("o de 8 na verdade tem 9", children=count, ages=[9])

                self.assertEqual(applied.record["child_ages"], [3, 9])

    def test_younger_and_older_point_at_the_child(self):
        kids = record(adults=2, children=2, child_ages=[7, 11])
        for message, ages, expected in (
            ("make the younger one 6", [6], [6, 11]),
            ("o mais novo tem 6", [6], [6, 11]),
            ("el menor tiene 6", [6], [6, 11]),
            ("the eldest is actually 12", [12], [7, 12]),
            ("o mais velho tem 12", [12], [7, 12]),
            ("el mayor en realidad tiene 12", [12], [7, 12]),
        ):
            with self.subTest(message=message):
                self.assertEqual(self.read(message, kids, ages=ages).record["child_ages"], expected)

    def test_a_correction_to_18_or_over_makes_that_one_an_adult(self):
        kids = record(adults=2, children=2, child_ages=[6, 9])

        applied = self.read("el mayor en realidad tiene 19", kids, ages=[19])

        self.assertEqual(
            (applied.record["adults"], applied.record["children"], applied.record["child_ages"]),
            (3, 1, [6]),
        )

    def test_when_nothing_says_which_child_nothing_changes_and_the_traveler_is_asked(self):
        for message, ages in (
            ("tem 7 agora", [7]),
            ("o de 5 tem 9", [9]),  # no child has the age the message names
            ("o mais novo tem 5 e o mais velho 9", [9]),  # both are named: not one correction
        ):
            with self.subTest(message=message):
                applied = self.read(message, ages=ages)

                self.assertEqual(applied.record["child_ages"], [3, 8])
                self.assertEqual([i.code for i in applied.issues], ["ambiguous_age_correction"])

    def test_the_merge_alone_never_lets_fewer_ages_replace_a_full_set(self):
        # no guard here: this is the state's own protection
        applied = apply_components(self.KIDS, comps(ages=[9]), TODAY)

        self.assertEqual(applied.record["child_ages"], [3, 8])
        self.assertEqual([i.code for i in applied.issues], ["ambiguous_age_correction"])

    def test_two_ages_of_three_children_do_not_replace_the_three_either(self):
        trio = record(adults=2, children=3, child_ages=[3, 8, 10])

        applied = self.read("tem 4 e 9", trio, ages=[4, 9])

        self.assertEqual(applied.record["child_ages"], [3, 8, 10])
        self.assertEqual([i.code for i in applied.issues], ["ambiguous_age_correction"])

    def test_a_full_new_set_still_replaces_the_old_one(self):
        applied = self.read("agora são 4 e 9", ages=[4, 9])

        self.assertEqual(applied.record["child_ages"], [4, 9])
        self.assertEqual(applied.issues, ())

    def test_the_model_doing_it_right_is_untouched(self):
        applied = self.read("o de 8 na verdade tem 9", correction={"from_age": 8, "to_age": 9})

        self.assertEqual(applied.record["child_ages"], [3, 9])

    def test_a_reply_that_completes_the_ages_is_not_a_correction(self):
        partial = record(adults=2, children=2, child_ages=[7])

        for ages in ([3], [3, 7]):
            with self.subTest(ages=ages):
                self.assertEqual(
                    self.read("o outro tem 3", partial, ages=ages).record["child_ages"],
                    [7, 3] if ages == [3] else [3, 7],
                )

    def test_a_bare_age_reply_for_the_only_child_is_what_it_was(self):
        one = record(adults=3, children=1)

        for raw in (
            dict(ages=[5]),
            dict(children=1, ages=[5]),
        ):  # the second is what the model said live
            with self.subTest(raw=raw):
                applied = self.read("5 anos", one, **raw)

                self.assertEqual(applied.record["child_ages"], [5])
                self.assertEqual((applied.record["adults"], applied.record["children"]), (3, 1))
                self.assertEqual(applied.issues, ())

    def test_one_age_for_one_of_two_children_still_waits_for_the_other(self):
        two = record(adults=2, children=2)

        first = self.read("a mais velha tem 7", two, ages=[7])
        second = self.read("o outro tem 3", first.record, ages=[3])

        self.assertEqual(first.record["child_ages"], [7])
        self.assertTrue(first.ask_child_ages)
        self.assertEqual(second.record["child_ages"], [7, 3])
        self.assertFalse(second.ask_child_ages)

    def test_a_message_that_is_only_an_age_carries_no_count(self):
        for message in (
            "5 anos",
            "5 años",
            "tem 5 anos.",
            "ela tem 5 anos",
            "tiene 5 años",
            "5 years old",
            "she's 5 years old",
            "He has 5 years",
        ):
            with self.subTest(message=message):
                guarded = guard_components(comps(adults=1, children=1, ages=[5]), message)

                self.assertEqual((guarded["adults"], guarded["children"]), (None, None))
                self.assertEqual(guarded["child_ages"], [5])

    def test_a_message_that_says_more_than_an_age_keeps_what_the_model_read(self):
        for message in (
            "criança de 5 anos",
            "meu filho tem 5 anos",
            "somos 2 e uma de 5 anos",
            "5 noites, 2 adultos",
            "uma criança, 5 anos",
        ):
            with self.subTest(message=message):
                guarded = guard_components(comps(children=1, ages=[5]), message)

                self.assertEqual(guarded["children"], 1)

    def test_the_frozen_age_reply_comes_out_as_the_phrase_expects_even_when_the_model_adds_a_count(
        self,
    ):
        from ai.orchestration import _extract_trip_details_signal
        from evaluations.trip_details_set import PHRASES, differences

        phrase = next(p for p in PHRASES if p.id == "age-reply")

        class Drifted(ScriptedProvider):
            """What the live model answered to "5 anos" once the prompt had grown."""

            def generate_structured_reply(
                self, messages, *, json_schema, max_tokens=None, temperature=None
            ):
                return {"children": 1, "child_ages": [5]}

        parsed = _extract_trip_details_signal(
            phrase.message,
            ai_provider=Drifted([]),
            history=[{"role": "assistant", "content": phrase.question}],
        )

        self.assertEqual(differences(parsed, phrase.expect), [])

    def test_the_prompt_no_longer_tells_the_model_to_answer_a_correction_with_the_age_alone(self):
        self.assertNotIn("is child_ages [9]", TRIP_DETAILS_SYSTEM_PROMPT)
        self.assertIn("never child_ages", TRIP_DETAILS_SYSTEM_PROMPT)
        self.assertIn("('5 anos') mentions no child", TRIP_DETAILS_SYSTEM_PROMPT)


class AgeCorrectionWholeTurnTests(_TripCase):
    def family(self, *later):
        return ScriptedProvider(
            [stays_turn(**WHEN, adults=2, children=2, child_ages=[3, 8]), *later]
        )

    def ages_in(self, result):
        return [value for key, value in query_of(self.url_of(result)) if key == "age"]

    def test_the_correction_through_the_turns_keeps_the_other_childs_age(self):
        provider = self.family(plain(child_ages=[9]))
        first, _, _ = self.say(
            provider, "Barcelona dia 5, 3 dias, 2 adultos e 2 crianças de 3 e 8 anos"
        )
        self.assertEqual(self.ages_in(first), ["3", "8"])

        corrected, _, _ = self.say(provider, "o de 8 na verdade tem 9")

        self.assertEqual(self.stored()["child_ages"], [3, 9])
        self.assertEqual((self.stored()["adults"], self.stored()["children"]), (2, 2))
        self.assertEqual(self.ages_in(corrected), ["3", "9"])
        self.assertTrue(corrected.retire_stays)  # the old button goes, the new one replaces it

    def test_the_model_answering_the_way_the_prompt_now_asks_gives_the_same_state(self):
        provider = self.family(plain(age_correction={"from_age": 8, "to_age": 9, "which": None}))
        self.say(provider, "Barcelona dia 5, 3 dias, 2 adultos e 2 crianças de 3 e 8 anos")

        corrected, _, _ = self.say(provider, "o de 8 na verdade tem 9")

        self.assertEqual(self.stored()["child_ages"], [3, 9])
        self.assertEqual(self.ages_in(corrected), ["3", "9"])

    def test_a_correction_that_does_not_say_which_child_is_asked_about_and_changes_nothing(self):
        provider = self.family(plain(child_ages=[7]))
        self.say(provider, "Barcelona dia 5, 3 dias, 2 adultos e 2 crianças de 3 e 8 anos")

        self.say(provider, "tem 7 agora")

        self.assertEqual(self.stored()["child_ages"], [3, 8])
        self.assertIn("not clear which child", self.prompt_of_last_reply(provider))

    def test_a_younger_one_in_spanish_through_the_turns(self):
        provider = self.family(plain(child_ages=[2]))
        self.say(provider, "Barcelona dia 5, 3 dias, 2 adultos y 2 niños de 3 y 8 años")

        corrected, _, _ = self.say(provider, "el menor tiene 2 en realidad")

        self.assertEqual(self.stored()["child_ages"], [2, 8])
        self.assertEqual(self.ages_in(corrected), ["2", "8"])

    def test_a_bare_age_after_the_question_completes_the_child_with_either_shape(self):
        for index, raw in enumerate(({"child_ages": [5]}, {"children": 1, "child_ages": [5]})):
            with self.subTest(raw=raw):
                self.user = User.objects.create_user(email=f"age{index}@example.com", password="x")
                self.key = memory.conversation_key(user=self.user, session_key=None)
                memory.clear_history(self.key)
                provider = ScriptedProvider(
                    [stays_turn(**WHEN, adults=3, children=1), plain(**raw)]
                )
                self.say(provider, "Barcelona dia 5, 3 dias, somos 3 adultos e uma criança")
                self.assertIn("a child's age is missing", self.prompt_of_last_reply(provider))

                ready, _, _ = self.say(provider, "5 anos")

                self.assertEqual(self.stored()["child_ages"], [5])
                self.assertEqual((self.stored()["adults"], self.stored()["children"]), (3, 1))
                self.assertEqual(self.ages_in(ready), ["5"])


# --- 4. a niece or nephew in the party ------------------------------------------------------------


class RelativeInThePartyTests(SimpleTestCase):
    THREE = record(adults=3)

    def read(self, message, current=None, **parts):
        current = current or self.THREE
        return apply_components(current, guard_components(comps(**parts), message, current), TODAY)

    def test_a_niece_or_nephew_with_an_age_under_18_is_a_child_and_the_adults_stay(self):
        # the model answered with "1 adult" - the traveler counted by default - every time
        for message, parts in (
            ("e vamos levar minha sobrinha de 7 anos", dict(adults=1, children=1, ages=[7])),
            ("e levamos o meu sobrinho de 9 anos", dict(adults=1, children=1, ages=[9])),
            ("vou também com o meu neto de 5 anos", dict(adults=1, children=1, ages=[5])),
            ("y llevamos a mi sobrina de 7 años", dict(adults=1, children=1, ages=[7])),
            ("mis nietos de 3 y 6 años también vienen", dict(adults=1, children=2, ages=[3, 6])),
            ("and we're bringing my nephew, he's 9", dict(adults=1, children=1, ages=[9])),
            ("my niece is joining us too, she's 7", dict(adults=2, children=1, ages=[7])),
            (
                "and my granddaughter, 4 years old, comes along",
                dict(adults=1, children=1, ages=[4]),
            ),
        ):
            with self.subTest(message=message):
                applied = self.read(message, **parts)

                self.assertEqual(applied.record["adults"], 3)
                self.assertEqual(applied.record["children"], parts["children"])
                self.assertEqual(applied.record["child_ages"], parts["ages"])
                self.assertEqual(applied.issues, ())

    def test_a_niece_or_nephew_of_18_or_over_is_an_adult_by_the_same_rule_as_a_grown_son(self):
        for message in (
            "vamos levar minha sobrinha de 25 anos",
            "y llevamos a mi sobrino de 30 años",
            "and we're bringing my 30 year old nephew",
            "o meu neto de 19 anos também vai",
        ):
            with self.subTest(message=message):
                # whether the model reported the age or left it out
                for parts in (dict(), dict(adults=1, children=1)):
                    applied = self.read(message, **parts)

                    self.assertEqual(applied.record["adults"], 4)
                    self.assertFalse(applied.record.get("children"))

    def test_with_no_age_nobody_is_called_an_adult_or_a_child_for_good_and_the_traveler_is_asked(
        self,
    ):
        applied = self.read("vamos com meu sobrinho", adults=1, children=1)

        self.assertEqual(applied.record["adults"], 3)  # nobody's place is taken
        self.assertEqual(applied.record["children"], 1)
        self.assertIsNone(applied.record["child_ages"])
        self.assertTrue(applied.ask_child_ages)  # the age decides what he is
        trip = resolve(applied.record, TODAY)
        self.assertFalse(trip.children_complete)
        self.assertIn("child_ages", trip.missing_for_search)

        # and the answer decides it: seven is a child, thirty an adult
        child = self.read("tem 7 anos", applied.record, ages=[7])
        adult = self.read("tem 30 anos", applied.record, ages=[30])
        self.assertEqual((child.record["adults"], child.record["children"]), (3, 1))
        self.assertEqual((adult.record["adults"], adult.record.get("children")), (4, 0))

    def test_a_relative_named_next_to_the_adults_does_not_hide_them(self):
        applied = self.read(
            "eu, minha esposa e minha sobrinha de 7 anos",
            record(),
            adults=2,
            children=1,
            ages=[7],
        )

        self.assertEqual((applied.record["adults"], applied.record["children"]), (2, 1))

    def test_a_cousin_or_a_parent_joining_in_passing_never_makes_the_party_smaller(self):
        # The model counted the traveler and the relative, and nobody else. The relative joins the
        # party on record (a grown-up relative is one more adult; a cousin or a sibling may be a
        # child, so the search waits for an age) - and the three adults are never taken down.
        for message, parts, adults, children in (
            ("e minha prima vai também", dict(adults=2), 3, 1),
            ("e meu irmão também vai", dict(adults=2), 3, 1),
            ("a minha tia vai connosco", dict(adults=2), 4, None),
            ("y mi madre también viene", dict(adults=2), 4, None),
            ("y mis abuelos también vienen", dict(adults=1), 3, None),  # more than one: left alone
            ("and my cousin is coming too", dict(adults=2), 3, 1),
            ("my mother is coming as well", dict(adults=2), 4, None),
        ):
            with self.subTest(message=message):
                applied = self.read(message, **parts)

                self.assertEqual(
                    (applied.record["adults"], applied.record.get("children")), (adults, children)
                )

    def test_a_relative_inside_a_statement_of_the_whole_party_is_believed(self):
        for message, parts, expected in (
            ("eu e meu irmão", dict(adults=2), 2),  # "eu": the traveler is restating the party
            ("só eu e minha mãe vamos", dict(adults=2), 2),
            ("somos 2: eu e meu primo", dict(adults=2), 2),
            ("2 adultos e meu primo", dict(adults=2), 2),
            ("me and my brother", dict(adults=2), 2),
            ("e meu primo vai também, com a mulher dele", dict(adults=2), 2),  # "mulher" counts
            ("e meu primo e a esposa dele vão", dict(adults=5), 5),  # more is not erasing
        ):
            with self.subTest(message=message):
                self.assertEqual(self.read(message, **parts).record["adults"], expected)

    def test_a_cousin_or_a_sibling_is_not_a_child_word(self):
        for message in ("vou com meu primo", "voy con mi hermano", "I'm bringing my cousin"):
            with self.subTest(message=message):
                guarded = guard_components(comps(adults=2), message)

                self.assertEqual(guarded["adults"], 2)

    def test_two_of_them_being_nephews_still_reclassifies_people_already_counted(self):
        applied = self.read("dois deles são sobrinhos", record(adults=5), children=2, among=True)

        self.assertEqual((applied.record["adults"], applied.record["children"]), (3, 2))
        self.assertTrue(applied.ask_child_ages)

    def test_taking_the_niece_back_clears_the_children_and_nothing_else(self):
        for message in (
            "afinal sem a minha sobrinha",
            "al final sin mi sobrina",
            "actually, no nephew after all",
        ):
            with self.subTest(message=message):
                kept = restrict_clears(comps(cleared=["children"]), message)

                self.assertEqual(kept["cleared_fields"], ["children"])

        self.assertEqual(
            restrict_clears(comps(cleared=["children"]), "afinal outra data")["cleared_fields"], []
        )

    def test_a_message_about_rooms_that_names_a_niece_is_also_about_who_is_going(self):
        guarded = guard_components(
            comps(adults=2, children=1, ages=[7]), "quero dois quartos, a minha sobrinha também vai"
        )

        # the niece is who is going, so the rooms rule leaves her alone; the message says
        # nothing about the adults, so the count the model read into it is dropped
        self.assertEqual(
            (guarded["adults"], guarded["children"], guarded["child_ages"]), (None, 1, [7])
        )
        # without the niece the same words say nothing about anyone
        nobody = guard_components(comps(adults=2, children=1, ages=[7]), "quero dois quartos")
        self.assertEqual(
            (nobody["adults"], nobody["children"], nobody["child_ages"]), (None, None, [])
        )

    def test_the_relative_words_open_the_gate_in_each_language(self):
        for message in (
            "e minha prima vai também",
            "mi madre también viene",
            "my brother is coming",
            "a minha avó vai connosco",
            "vamos com a minha sobrinha",
            "levo o meu sobrinho",
            "y vamos con mi sobrina",
            "llevo a mis nietos",
            "my nephew is coming too",
            "we are taking our grandkids",
            "e o meu neto",
            "com a minha afilhada",
        ):
            with self.subTest(message=message):
                self.assertTrue(has_trip_detail_cues(message))


class RelativeWholeTurnTests(_TripCase):
    def test_the_niece_joins_the_party_and_the_three_adults_stay_three(self):
        provider = ScriptedProvider(
            [
                stays_turn(**WHEN, adults=3),
                plain(adults=1, children=1, child_ages=[7]),  # how the model answered live
            ]
        )
        ready, _, _ = self.say(provider, "Barcelona dia 5, 3 dias, somos 3 adultos")
        self.assertEqual(dict(query_of(self.url_of(ready)))["group_adults"], "3")

        joined, _, _ = self.say(provider, "e vamos levar minha sobrinha de 7 anos")

        self.assertEqual((self.stored()["adults"], self.stored()["children"]), (3, 1))
        query = dict(query_of(self.url_of(joined)))
        self.assertEqual(
            (query["group_adults"], query["group_children"], query["age"]), ("3", "1", "7")
        )

    def test_with_no_age_the_search_waits_and_the_adults_are_untouched(self):
        provider = ScriptedProvider([stays_turn(**WHEN, adults=3), plain(adults=1, children=1)])
        self.say(provider, "Barcelona dia 5, 3 dias, somos 3 adultos")

        waiting, _, _ = self.say(provider, "vamos com o meu sobrinho")

        self.assertEqual(self.stored()["adults"], 3)
        self.assertFalse(self.has_search(waiting))
        self.assertTrue(waiting.retire_stays)  # the old search no longer matches the party
        self.assertIn("a child's age is missing", self.prompt_of_last_reply(provider))

    def test_a_cousin_joining_in_passing_leaves_the_three_adults_three_and_waits_for_an_age(self):
        provider = ScriptedProvider([stays_turn(**WHEN, adults=3), plain(adults=2)])
        self.say(provider, "Barcelona dia 5, 3 dias, somos 3 adultos")

        joined, _, _ = self.say(provider, "e minha prima vai também")

        self.assertEqual((self.stored()["adults"], self.stored()["children"]), (3, 1))
        self.assertFalse(self.has_search(joined))  # no age assumed: the search waits for it
        self.assertTrue(joined.retire_stays)  # the old search no longer matches the party
        self.assertIn("a child's age is missing", self.prompt_of_last_reply(provider))

    def test_the_gate_lets_a_relative_with_no_number_in_the_message_through(self):
        provider = ScriptedProvider([stays_turn(**WHEN, adults=3), plain(adults=1, children=1)])
        self.say(provider, "Barcelona dia 5, 3 dias, somos 3 adultos")
        calls = self.trip_calls(provider)

        self.say(provider, "vamos com a minha sobrinha")

        self.assertEqual(self.trip_calls(provider), calls + 1)
        self.assertEqual(self.stored()["adults"], 3)
