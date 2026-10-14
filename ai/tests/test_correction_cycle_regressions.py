"""The six product defects of the third correction cycle, each pinned at the unit
that decides it and through a whole turn: a month said alone, a link or an
"opened it" with no card, relative changes of the stay, unverified prices, visa
and entry rules, and what "two of them are children" or a 19-year-old son means."""

from datetime import date, timedelta
from unittest import mock

from django.test import SimpleTestCase

from ai import memory
from ai.orchestration import (
    _PRICE_NOTES,
    _asks_to_open_search,
    _asserted_visa_phrase,
    _build_visa_question_messages,
    _entry_requirements_note,
    _price_verdict,
    _visa_verified_data_note,
    _without_unverified_prices,
)
from ai.tests.helpers import ScriptedProvider
from ai.tests.test_selected_destination import WHEN, spain, turn
from ai.tests.test_trip_details import TODAY, apply, comps, record
from ai.tests.test_trip_details_flow import _TripCase, plain, query_of
from ai.trip_details import (
    TripTurn,
    apply_components,
    fact_block,
    guard_components,
    resolve,
)
from travel.models import CountryEntryRequirement, Destination
from travel.services import entry_requirement_can_be_asserted
from users.models import TravelerProfile

STAY = record(start_date="2026-12-10", stay_length=7, stay_unit="nights", adults=2)


def delta(nights, at=None, shift=None):
    return {"nights_delta": nights, "at": at, "shift_days": shift}


# --- 1. a month said alone ---------------------------------------------------


class MonthAloneTests(SimpleTestCase):
    def test_a_month_alone_is_kept_as_partial_information_and_no_date(self):
        applied = apply(month=1)

        self.assertIsNone(applied.record["start_date"])
        self.assertEqual(applied.record["start_month"], 1)
        self.assertNotIn("start_year", applied.record)
        self.assertEqual(applied.issues, ())

    def test_no_booking_dates_come_out_of_a_month_alone(self):
        applied = apply(month=1, length=7, unit="nights", adults=2)

        trip = resolve(applied.record, TODAY)

        self.assertIsNone(trip.check_in)
        self.assertEqual(trip.missing_for_search, ("check_in",))
        self.assertIsNone(trip.search_kwargs())

    def test_a_later_bare_day_completes_it_as_the_next_future_occurrence(self):
        for stored_month, day, expected in (
            (1, 10, "2027-01-10"),  # January 10th of this year has gone by
            (11, 3, "2026-11-03"),  # November still lies ahead this year
            (10, 20, "2026-10-20"),  # later this month
            (10, 3, "2027-10-03"),  # earlier this month: next year's
        ):
            with self.subTest(month=stored_month, day=day):
                partial = apply(month=stored_month).record

                applied = apply(partial, day=day)

                self.assertEqual(applied.record["start_date"], expected)
                self.assertNotIn("start_month", applied.record)
                self.assertFalse(applied.record["start_assumed_month"])

    def test_a_year_the_traveler_said_is_kept_and_used(self):
        partial = apply(month=1, year=2028).record

        self.assertEqual(partial["start_year"], 2028)
        self.assertEqual(apply(partial, day=10).record["start_date"], "2028-01-10")

    def test_a_month_that_has_already_gone_by_in_a_stated_year_is_asked_about(self):
        applied = apply(month=3, year=2026)

        self.assertEqual([i.code for i in applied.issues], ["month_in_past"])
        self.assertIsNone(applied.record)

    def test_a_full_date_replaces_the_partial_month(self):
        partial = apply(month=1).record

        applied = apply(partial, day=5, month=12)

        self.assertEqual(applied.record["start_date"], "2026-12-05")
        self.assertNotIn("start_month", applied.record)

    def test_a_later_month_replaces_an_earlier_one(self):
        applied = apply(apply(month=1).record, month=2)

        self.assertEqual(applied.record["start_month"], 2)

    def test_a_different_month_replaces_a_known_date_the_same_month_keeps_it(self):
        different = apply(STAY, month=1)
        same = apply(STAY, month=12)

        self.assertIsNone(different.record["start_date"])
        self.assertEqual(different.record["start_month"], 1)
        self.assertEqual(same.record["start_date"], "2026-12-10")
        self.assertTrue(different.details_changed)
        self.assertFalse(same.details_changed)

    def test_next_month_with_no_day_is_kept_with_its_year(self):
        applied = apply(relative="next")

        self.assertEqual((applied.record["start_month"], applied.record["start_year"]), (11, 2026))

    def test_clearing_the_dates_clears_it_and_a_reset_does_too(self):
        partial = apply(month=1).record

        self.assertIsNone(apply(partial, cleared=["start"]).record)
        self.assertIsNone(apply(partial, cleared=["everything"]).record)

    def test_the_reply_is_told_the_month_and_to_ask_only_for_the_day(self):
        applied = apply(month=1, length=7, unit="nights")
        trip = resolve(applied.record, TODAY)

        facts = fact_block(TripTurn(trip=trip, today=TODAY), always=True, ask_missing=True)

        self.assertIn("named January but no day", facts)
        self.assertIn("Never state a day or a year they did not say", facts)
        self.assertIn("Ask which day of January", facts)

    def test_a_partial_month_in_a_record_saved_before_this_existed_reads_as_nothing(self):
        old = {"start_date": None, "stay_length": 3, "stay_unit": "days", "adults": 2}

        self.assertIsNone(resolve(old, TODAY).start_month)


class MonthAloneWholeTurnTests(_TripCase):
    def test_roma_em_janeiro_then_dia_10_is_january_10th_of_the_next_january(self):
        provider = ScriptedProvider(
            [
                turn(
                    spain(selected_destination_name="Madrid"), trip_details={"start": {"month": 1}}
                ),
                plain(start={"day": 10}),
                plain(stay_length=5, stay_unit="nights", adults=2),
            ]
        )

        self.say(provider, "Quero ir pra Madrid em janeiro")
        self.assertIsNone(self.stored()["start_date"])
        self.assertEqual(self.stored()["start_month"], 1)
        self.assertIn("named January but no day", self.prompt_of_last_reply(provider))

        self.say(provider, "dia 10")
        self.assertEqual(self.stored()["start_date"], "2027-01-10")

        result, _, _ = self.say(provider, "5 noites, somos 2")
        self.assertTrue(self.has_search(result))
        self.assertIn("checkin=2027-01-10", self.url_of(result))

    def test_the_search_waits_for_the_day(self):
        provider = ScriptedProvider(
            [
                turn(
                    spain(selected_destination_name="Madrid"), trip_details={"start": {"month": 1}}
                ),
                plain(stay_length=5, stay_unit="nights", adults=2),
            ]
        )
        self.say(provider, "Quero ir pra Madrid em janeiro")

        result, _, _ = self.say(provider, "5 noites, somos 2")

        self.assertFalse(self.has_search(result))
        self.assertIn("Ask which day of January", self.prompt_of_last_reply(provider))


# --- 2. links and actions the application did not make ------------------------


class OpenTheSearchTests(SimpleTestCase):
    SEARCH_REPLY = [{"role": "assistant", "content": "The search for your stay is ready."}]

    def test_a_request_to_open_or_show_the_search_is_recognized(self):
        for message in (
            "abre la búsqueda otra vez",
            "abre a busca de novo",
            "show me the stays again",
            "can you open the booking link?",
            "mostra de novo as hospedagens",
            "pode abrir os resultados?",
        ):
            with self.subTest(message=message):
                self.assertTrue(_asks_to_open_search(message, []))

    def test_a_bare_open_it_counts_right_after_a_reply_about_the_search(self):
        self.assertTrue(_asks_to_open_search("ok open it", self.SEARCH_REPLY))
        self.assertTrue(_asks_to_open_search("abre aí", self.SEARCH_REPLY))
        self.assertFalse(_asks_to_open_search("ok open it", []))

    def test_other_uses_of_those_verbs_are_not(self):
        for message in (
            "a que horas abre o Louvre?",
            "what time does the museum open?",
            "mostra os pontos turísticos",
            "show me the best beaches",
            "dame ideas para el viaje",
        ):
            with self.subTest(message=message):
                self.assertFalse(_asks_to_open_search(message, self.SEARCH_REPLY))


class OpenTheSearchWholeTurnTests(_TripCase):
    READY = turn(
        spain(
            is_accommodation_request=True,
            accommodation_place_name="Barcelona",
            selected_destination_name="Barcelona",
        ),
        trip_details={**WHEN, "adults": 2},
    )
    REPLY = "The search for your stay is ready.\n\n[Open it](insert-link-here)"

    def test_open_it_gets_the_application_card_not_a_link_the_model_wrote(self):
        provider = ScriptedProvider([self.READY, turn(spain())], reply_text=self.REPLY)
        self.say(provider, "quero ir pra Barcelona dia 5, 3 dias, somos 2")

        result, _, _ = self.say(provider, "ok open it")

        self.assertTrue(self.has_search(result))
        self.assertIn("a stay search for Barcelona", self.prompt_of_last_reply(provider))
        spoken = memory.get_history(self.key)[-1]["content"]
        self.assertNotIn("insert-link-here", spoken)
        self.assertNotIn("](", spoken)

    def test_the_same_request_before_the_trip_is_ready_asks_what_is_missing(self):
        provider = ScriptedProvider(
            [turn(spain(selected_destination_name="Barcelona")), turn(spain())],
            reply_text=self.REPLY,
        )
        self.say(provider, "quero ir pra Barcelona")

        result, _, _ = self.say(provider, "abre a busca")

        self.assertFalse(self.has_search(result))
        prompt = self.prompt_of_last_reply(provider)
        self.assertIn("There is NO Booking search action yet", prompt)
        self.assertIn("Needs clarification", prompt)

    def test_a_question_about_opening_hours_is_not_taken_for_the_search(self):
        provider = ScriptedProvider([self.READY, turn(spain())], reply_text=self.REPLY)
        self.say(provider, "quero ir pra Barcelona dia 5, 3 dias, somos 2")

        result, _, _ = self.say(provider, "a que horas abre o Louvre?")

        self.assertFalse(self.has_search(result))
        self.assertNotIn("a stay search for", self.prompt_of_last_reply(provider))

    def test_a_request_to_see_the_stays_again_is_not_a_recall_even_when_labeled_one(self):
        provider = ScriptedProvider(
            [self.READY, turn(spain(is_recall_request=True))], reply_text=self.REPLY
        )
        self.say(provider, "quero ir pra Barcelona dia 5, 3 dias, somos 2")

        result, _, _ = self.say(provider, "me mostra de novo as hospedagens")

        self.assertTrue(self.has_search(result))


# --- 3. relative changes of the stay ------------------------------------------


class RelativeStayChangeTests(SimpleTestCase):
    def change(self, current=STAY, **kwargs):
        return apply_components(current, comps(**kwargs), TODAY)

    def test_add_one_night_lengthens_the_stay_and_leaves_the_start(self):
        record_ = self.change(change=delta(1)).record

        self.assertEqual((record_["start_date"], record_["stay_length"]), ("2026-12-10", 8))

    def test_remove_one_night_shortens_it(self):
        self.assertEqual(self.change(change=delta(-1)).record["stay_length"], 6)

    def test_add_a_night_at_the_start_moves_the_start_and_the_length_together(self):
        record_ = self.change(change=delta(1, at="start")).record

        self.assertEqual((record_["start_date"], record_["stay_length"]), ("2026-12-09", 8))
        # the check-out did not move
        self.assertEqual(resolve(record_, TODAY).check_out, resolve(STAY, TODAY).check_out)

    def test_remove_a_night_at_the_start_does_the_opposite(self):
        record_ = self.change(change=delta(-1, at="start")).record

        self.assertEqual((record_["start_date"], record_["stay_length"]), ("2026-12-11", 6))

    def test_at_the_end_is_the_default(self):
        self.assertEqual(self.change(change=delta(2, at="end")).record["stay_length"], 9)

    def test_make_it_eight_nights_replaces_the_duration(self):
        self.assertEqual(self.change(length=8, unit="nights").record["stay_length"], 8)

    def test_a_total_beats_a_change_if_the_model_returns_both(self):
        self.assertEqual(
            self.change(length=8, unit="nights", change=delta(1)).record["stay_length"], 8
        )

    def test_a_change_with_no_length_on_record_is_a_question_and_changes_nothing(self):
        applied = self.change(record(start_date="2026-12-10", adults=2), change=delta(1))

        self.assertEqual([i.code for i in applied.issues], ["relative_without_length"])
        self.assertFalse(applied.details_changed)

    def test_a_change_at_the_start_with_no_start_date_is_a_question(self):
        applied = self.change(
            record(stay_length=7, stay_unit="nights"), change=delta(1, at="start")
        )

        self.assertEqual([i.code for i in applied.issues], ["relative_without_start"])
        self.assertFalse(applied.details_changed)

    def test_a_stay_that_would_be_nothing_is_a_question(self):
        applied = self.change(
            record(start_date="2026-12-10", stay_length=1, stay_unit="nights"), change=delta(-1)
        )

        self.assertEqual([i.code for i in applied.issues], ["invalid_stay_change"])
        self.assertEqual(applied.record["stay_length"], 1)

    def test_a_start_that_would_land_in_the_past_is_a_question(self):
        today_start = record(start_date=TODAY.isoformat(), stay_length=3, stay_unit="nights")

        applied = self.change(today_start, change=delta(1, at="start"))

        self.assertEqual([i.code for i in applied.issues], ["start_in_past"])
        self.assertEqual(applied.record["start_date"], TODAY.isoformat())

    def test_dates_that_shift_with_no_word_on_the_check_out_are_a_question(self):
        applied = self.change(change=delta(None, shift=1))

        self.assertEqual([i.code for i in applied.issues], ["ambiguous_shift"])
        self.assertFalse(applied.details_changed)

    def test_the_same_turn_processed_twice_applies_it_once(self):
        first = apply_components(STAY, comps(change=delta(1)), TODAY, turn=3)
        again = apply_components(first.record, comps(change=delta(1)), TODAY, turn=3)
        next_turn = apply_components(again.record, comps(change=delta(1)), TODAY, turn=4)

        self.assertEqual(first.record["stay_length"], 8)
        self.assertEqual(again.record["stay_length"], 8)
        self.assertEqual(next_turn.record["stay_length"], 9)

    def test_the_turn_marker_is_not_a_trip_detail(self):
        applied = apply_components(STAY, comps(change=delta(1)), TODAY, turn=3)

        self.assertTrue(applied.details_changed)
        cleared = apply_components(applied.record, comps(cleared=["everything"]), TODAY, turn=4)
        self.assertIsNone(cleared.record)

    def test_a_record_that_holds_only_the_marker_is_no_record(self):
        applied = apply_components(
            record(stay_length=3, stay_unit="nights", delta_turn=2),
            comps(cleared=["stay"]),
            TODAY,
        )

        self.assertIsNone(applied.record)


class RelativeStayChangeWholeTurnTests(_TripCase):
    def test_add_one_night_through_a_turn_moves_the_link_by_one_night(self):
        ready = turn(
            spain(
                is_accommodation_request=True,
                accommodation_place_name="Barcelona",
                selected_destination_name="Barcelona",
            ),
            trip_details={**WHEN, "adults": 2},
        )
        provider = ScriptedProvider(
            [ready, plain(stay_change=delta(1)), plain(stay_change=delta(1, at="start"))]
        )

        first, _, _ = self.say(provider, "Barcelona dia 5, 3 dias, somos 2")
        second, _, _ = self.say(provider, "add one night")
        third, _, _ = self.say(provider, "add one night at the start")

        self.assertEqual(self.stored()["stay_length"], 5)
        self.assertEqual([self.nights(r) for r in (first, second, third)], [3, 4, 5])
        # "at the start" moved the start a day earlier and left the check-out
        self.assertEqual(dict(self.query(third))["checkout"], dict(self.query(second))["checkout"])
        self.assertEqual(
            date.fromisoformat(dict(self.query(third))["checkin"]),
            date.fromisoformat(dict(self.query(second))["checkin"]) - timedelta(days=1),
        )

    def query(self, result):
        return query_of(self.url_of(result))

    def nights(self, result):
        link = dict(self.query(result))
        return (date.fromisoformat(link["checkout"]) - date.fromisoformat(link["checkin"])).days

    def test_a_change_with_nothing_to_change_asks(self):
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                plain(stay_change=delta(1)),
            ]
        )
        self.say(provider, "quero ir pra Barcelona")

        result, _, _ = self.say(provider, "add one night")

        self.assertFalse(self.has_search(result))
        self.assertIn("no length of stay is on record", self.prompt_of_last_reply(provider))


# --- 4. prices nobody gave the model --------------------------------------------------


class PriceVerdictTests(SimpleTestCase):
    GIVEN = {"2000"}

    def verdict(self, sentence, given=None):
        return _price_verdict(sentence, self.GIVEN if given is None else given)

    def test_the_price_of_a_specific_thing_is_unverified_whatever_the_wording(self):
        for sentence in (
            "Uma diária em Paris custa cerca de 100 euros.",
            "Un menú puede costar entre 10 y 25 euros.",
            "Normalmente entre R$ 2.500 e R$ 4.500 por um voo.",
            "Rooms start around $120 a night.",
            "Dinner is about €35 per person.",
            "A ticket to the museum is roughly 18 euros.",
            "Um quarto sai por uns 90 dólares.",
            "It costs about 100 euros.",
        ):
            with self.subTest(sentence=sentence):
                self.assertEqual(self.verdict(sentence), "specific")

    def test_a_trip_planning_budget_that_says_it_is_an_estimate_stays(self):
        for sentence in (
            "A week in Lisbon can cost around 1,200 euros per person.",
            "Um orçamento aproximado de 1.500 euros para a semana.",
            "Para el viaje, calcula unos 900 euros de presupuesto.",
        ):
            with self.subTest(sentence=sentence):
                self.assertEqual(self.verdict(sentence), "labeled")

    def test_a_budget_that_does_not_say_so_stays_but_the_reply_will_say_it_for_it(self):
        self.assertEqual(self.verdict("A week in Lisbon costs 1,200 euros."), "unlabeled")

    def test_what_the_traveler_gave_is_theirs_to_hear_again(self):
        self.assertIsNone(self.verdict("Com os seus 2000 euros dá para uma semana."))
        self.assertIsNone(self.verdict("Under $100 a night, then.", {"100"}))
        self.assertIsNone(self.verdict("R$ 2.000 é o seu orçamento.", {"2000"}))

    def test_numbers_that_are_not_money_are_left_alone(self):
        self.assertIsNone(
            self.verdict(
                "5 noites, 2 adultos, 22°C, custo 3/5, check-in 10 de dezembro, 1,5 km do centro."
            )
        )


class PriceFilterTests(SimpleTestCase):
    TEXT = (
        "Lisboa é ótima. Uma diária custa cerca de 100 euros. "
        "Uma semana pode custar em torno de 1.200 euros de orçamento, aproximadamente.\n"
        "- Jantar: 35 euros\n- Passeio de elétrico\n"
    )

    def run_filter(self, chunks, given=frozenset()):
        outcome = {"dropped": False, "unlabeled": False}
        return "".join(_without_unverified_prices(iter(chunks), set(given), outcome)), outcome

    def test_the_unverified_price_goes_and_the_rest_stays(self):
        text, outcome = self.run_filter([self.TEXT])

        self.assertNotIn("100 euros", text)
        self.assertNotIn("35 euros", text)
        self.assertIn("Lisboa é ótima.", text)
        self.assertIn("1.200 euros de orçamento, aproximadamente", text)
        self.assertIn("Passeio de elétrico", text)
        self.assertEqual(outcome, {"dropped": True, "unlabeled": False})

    def test_where_the_stream_is_cut_cannot_change_the_result(self):
        whole, _ = self.run_filter([self.TEXT])

        for cut in range(1, len(self.TEXT)):
            with self.subTest(cut=cut):
                text, _ = self.run_filter([self.TEXT[:cut], self.TEXT[cut:]])
                self.assertEqual(text, whole)

    def test_a_reply_with_nothing_to_remove_passes_through_whole(self):
        reply = "Lisboa tem 22°C em dezembro.\n\nBoa viagem!"

        text, outcome = self.run_filter([reply[:10], reply[10:]])

        self.assertEqual(text, reply)
        self.assertEqual(outcome, {"dropped": False, "unlabeled": False})

    def test_a_stream_that_fails_part_way_still_hands_over_what_arrived(self):
        def failing():
            yield "Partial reply... "
            raise RuntimeError("connection dropped")

        outcome = {"dropped": False, "unlabeled": False}
        seen = []
        with self.assertRaises(RuntimeError):
            for chunk in _without_unverified_prices(failing(), set(), outcome):
                seen.append(chunk)

        self.assertEqual("".join(seen), "Partial reply... ")


class UnverifiedPriceWholeTurnTests(_TripCase):
    """The note that follows a dropped price is the application's own fixed sentence: a
    model asked to word it answered the price question in it (see test_final_pass_regressions
    for the language, the model never being asked, and the hotel ranges)."""

    def conversation(self, reply_text):
        provider = ScriptedProvider(
            [turn(spain(selected_destination_name="Barcelona")), plain()], reply_text=reply_text
        )
        self.say(provider, "quero ir pra Barcelona")
        return provider

    def spoken(self, provider, message):
        self.say(provider, message)
        return memory.get_history(self.key)[-1]["content"]

    def test_a_made_up_hotel_price_never_reaches_the_traveler_nor_the_history(self):
        provider = self.conversation(
            "Barcelona é cara. Uma diária custa cerca de 100 euros. Vale a pena ir."
        )

        spoken = self.spoken(provider, "e uma diária média?")

        self.assertNotIn("100", spoken)
        self.assertIn("Barcelona é cara.", spoken)
        self.assertTrue(spoken.endswith(_PRICE_NOTES["pt"]["dropped"]))
        self.assertEqual(provider.reply_calls, 0)  # the model was not asked to word the note

    def test_a_general_budget_that_says_it_is_an_estimate_is_kept_without_a_note(self):
        provider = self.conversation(
            "Uma semana pode custar aproximadamente 1.200 euros de orçamento."
        )

        spoken = self.spoken(provider, "quanto devo levar?")

        self.assertIn("1.200 euros", spoken)
        self.assertNotIn(_PRICE_NOTES["pt"]["dropped"], spoken)
        self.assertNotIn(_PRICE_NOTES["pt"]["rough"], spoken)

    def test_a_budget_that_does_not_say_so_is_kept_and_followed_by_the_estimate_note(self):
        provider = self.conversation("Uma semana custa 1.200 euros no total.")

        spoken = self.spoken(provider, "quanto devo levar?")

        self.assertIn("1.200 euros", spoken)
        self.assertTrue(spoken.endswith(_PRICE_NOTES["pt"]["rough"]))
        self.assertEqual(provider.reply_calls, 0)

    def test_the_travelers_own_budget_echoed_back_is_untouched(self):
        provider = self.conversation("Com os seus 2000 euros dá para uma semana.")

        spoken = self.spoken(provider, "tenho 2000 euros, dá?")

        self.assertEqual(spoken, "Com os seus 2000 euros dá para uma semana.")
        self.assertEqual(provider.reply_calls, 0)


# --- 5. visa and entry rules -----------------------------------------------------


class EntryRulesTests(_TripCase):
    """Entry rules are stated only from an entry the owner has verified against an official
    source; the curated file as it stands is not, and contradicts itself."""

    def setUp(self):
        super().setUp()
        # Spain as the curated file has it for every Schengen country: Brazil is listed as
        # needing a visa while the notes say Brazilians enter visa-free for 90 days.
        self.spain = CountryEntryRequirement.objects.create(
            country="Spain",
            visa_required_nationalities=["Brazil", "India"],
            visa_notes="Schengen: Brazilians and Argentines enter visa-free for 90 days.",
        )
        self.japan = CountryEntryRequirement.objects.create(
            country="Japan",
            visa_required_nationalities=["India"],
            visa_notes="Short stays are visa-exempt for most nationalities.",
        )

    def verified(self, *countries):
        return mock.patch("travel.services.VERIFIED_ENTRY_COUNTRIES", frozenset(countries))

    def test_nothing_is_asserted_from_an_entry_nobody_has_verified(self):
        for nationality in ("India", "Canada", "Brazil"):
            with self.subTest(nationality=nationality):
                self.assertFalse(entry_requirement_can_be_asserted(self.japan, nationality))
                self.assertIsNone(_asserted_visa_phrase(self.japan, nationality))

    def test_the_brazil_schengen_contradiction_is_never_asserted_even_for_a_verified_entry(self):
        with self.verified("Spain"):
            self.assertFalse(entry_requirement_can_be_asserted(self.spain, "Brazil"))
            self.assertIsNone(_asserted_visa_phrase(self.spain, "Brazil"))
            # a nationality the notes do not contradict is another matter
            self.assertIn("a visa IS required", _asserted_visa_phrase(self.spain, "India"))

    def test_a_missing_nationality_asserts_nothing(self):
        with self.verified("Japan"):
            self.assertFalse(entry_requirement_can_be_asserted(self.japan, None))
            self.assertFalse(entry_requirement_can_be_asserted(self.japan, ""))

    def test_the_data_itself_is_kept_untouched_for_review(self):
        stored = CountryEntryRequirement.objects.get(country="Spain")

        self.assertEqual(stored.visa_required_nationalities, ["Brazil", "India"])
        self.assertIn("visa-free", stored.visa_notes)

    def test_a_brazilian_asking_about_spain_is_told_it_cannot_be_verified(self):
        intent = {"visa_question_country": "Spain", "visa_question_nationality": "Brazil"}
        for verified in ((), ("Spain",)):  # unverified, and verified-but-contradictory
            with self.subTest(verified=verified), self.verified(*verified):
                prompt = _build_visa_question_messages(
                    "preciso de visto para a Espanha? sou brasileiro", intent, None, []
                )[-1].content

                self.assertIn("Do NOT say, from memory", prompt)
                self.assertIn("immigration/government website", prompt)
                for rule in ("IS required", "NOT required", "Verified data on file"):
                    self.assertNotIn(rule, prompt)

    def test_a_missing_nationality_gets_the_same_limitation(self):
        with self.verified("Japan"):
            prompt = _build_visa_question_messages(
                "preciso de visto para o Japão?",
                {"visa_question_country": "Japan", "visa_question_nationality": None},
                None,
                [],
            )[-1].content

        self.assertIn("Do NOT say, from memory", prompt)
        self.assertNotIn("Verified data on file", prompt)

    def test_an_entry_the_owner_has_verified_is_used_and_nothing_else_is(self):
        with self.verified("Japan"):
            prompt = _build_visa_question_messages(
                "do I need a visa for Japan?",
                {"visa_question_country": "Japan", "visa_question_nationality": "India"},
                None,
                [],
            )[-1].content

        self.assertIn("Verified data on file for Japan", prompt)
        self.assertIn("using ONLY the data given to you above", prompt)
        self.assertIn("not an official source", prompt)

    def test_the_country_of_the_place_already_chosen_is_the_country_asked_about(self):
        with self.verified("Japan"):
            note = _visa_verified_data_note(
                {"visa_question_country": None, "visa_question_nationality": "India"}, None, "Japan"
            )

        self.assertIn("Verified data on file for Japan", note)

    def test_a_general_question_does_not_borrow_the_chosen_place(self):
        with self.verified("Japan"):
            prompt = _build_visa_question_messages(
                "quais países não precisam de visto para indianos?",
                {"visa_question_country": None, "visa_question_nationality": "India"},
                None,
                [],
                selected_country="Japan",
            )[-1].content

        self.assertNotIn("Verified data on file for Japan", prompt)
        self.assertIn("covering 1 countries", prompt)

    def test_the_profile_note_in_a_destination_reply_asserts_nothing_unverified(self):
        profile = TravelerProfile.objects.create(user=self.user, home_country="Brazil")
        destination = Destination.objects.get(slug="barcelona-es")

        self.assertEqual(_entry_requirements_note(profile, [destination]), "")

    def test_through_a_turn_with_nothing_verified_the_reply_is_held_to_the_limitation(self):
        TravelerProfile.objects.create(user=self.user, home_country="India")
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                turn(spain(is_visa_or_entry_question=True, visa_question_country=None)),
            ]
        )
        self.say(provider, "quero ir pra Barcelona")

        self.say(provider, "preciso de visto?")

        prompt = self.prompt_of_last_reply(provider)
        self.assertIn("Do NOT say, from memory", prompt)
        self.assertNotIn("Verified data on file", prompt)


# --- 6. who is in the party ---------------------------------------------------------


class PartyMeaningTests(SimpleTestCase):
    def test_two_of_them_are_children_reclassifies_people_already_counted(self):
        applied = apply(record(adults=5), children=2, among=True)

        self.assertEqual((applied.record["adults"], applied.record["children"]), (3, 2))

    def test_the_known_total_includes_children_already_on_record(self):
        stored = record(adults=3, children=1, child_ages=[5])

        applied = apply(stored, children=2, among=True)

        # four people: two of them children now, and the known age is kept
        self.assertEqual((applied.record["adults"], applied.record["children"]), (2, 2))
        self.assertEqual(applied.record["child_ages"], [5])
        self.assertTrue(applied.ask_child_ages)

    def test_all_of_them_being_children_leaves_no_adult_and_is_a_question(self):
        applied = apply(record(adults=2), children=2, among=True)

        self.assertEqual([i.code for i in applied.issues], ["party_conflict"])
        self.assertEqual(applied.record["adults"], 2)
        self.assertNotIn("children", {k for k, v in applied.record.items() if v})

    def test_adults_the_traveler_states_win(self):
        applied = apply(record(adults=5), adults=3, children=2, among=True)

        self.assertEqual((applied.record["adults"], applied.record["children"]), (3, 2))

    def test_children_added_to_the_party_are_not_a_reclassification(self):
        applied = apply(record(adults=2), children=2)

        self.assertEqual((applied.record["adults"], applied.record["children"]), (2, 2))

    def test_the_model_flag_needs_the_message_to_say_of_them(self):
        flagged = comps(children=2, among=True)

        self.assertFalse(guard_components(flagged, "and two kids")["children_among_counted"])
        for message in (
            "dos de ellos son niños",
            "dois deles são crianças",
            "two of them are kids",
        ):
            with self.subTest(message=message):
                self.assertTrue(guard_components(flagged, message)["children_among_counted"])

    def test_without_a_total_on_record_it_is_just_the_children(self):
        applied = apply(None, children=2, among=True)

        self.assertEqual(applied.record["children"], 2)
        self.assertIsNone(applied.record["adults"])


class GrownChildTests(SimpleTestCase):
    def read(self, message, **parts):
        guarded = guard_components(comps(**parts), message)
        return apply_components(None, guarded, TODAY).record

    def test_a_19_year_old_son_is_an_adult_for_booking(self):
        for message in (
            "somos eu, minha mulher e nosso filho de 19 anos",
            "somos nosotros dos y nuestro hijo de 19 años",
            "it's me, my wife and our son, 19 years old",
            "me, my wife and my 19 year old son",
        ):
            with self.subTest(message=message):
                record_ = self.read(message, adults=2)

                self.assertEqual(record_["adults"], 3)
                self.assertFalse(record_.get("children"))

    def test_the_model_having_reported_him_already_is_not_counted_twice(self):
        record_ = self.read(
            "eu, minha mulher e nosso filho de 19 anos", adults=2, children=1, ages=[19]
        )

        self.assertEqual(record_["adults"], 3)

    def test_a_child_under_18_stays_a_child_and_a_grown_child_beside_one_is_an_adult(self):
        record_ = self.read(
            "eu, minha mulher, nosso filho de 19 anos e a filha de 12",
            adults=2,
            children=1,
            ages=[12],
        )

        self.assertEqual((record_["adults"], record_["children"]), (2, 1))

    def test_ages_that_are_not_a_sons_or_daughters_are_left_alone(self):
        for message in (
            "tenho 35 anos e viajo com minha filha",
            "los amigos son de 25 años",
            "my wife is 40 years old and we have a kid",
        ):
            with self.subTest(message=message):
                guarded = guard_components(comps(adults=2, children=1), message)

                self.assertEqual(guarded["child_ages"], [])


class AgeCorrectionTests(SimpleTestCase):
    TWO_KIDS = record(adults=2, children=2, child_ages=[3, 8])

    def correct(self, current=None, **correction):
        return apply_components(current or self.TWO_KIDS, comps(correction=correction), TODAY)

    def test_the_age_that_changes_is_found_by_its_old_value(self):
        applied = self.correct(from_age=8, to_age=9)

        self.assertEqual(applied.record["child_ages"], [3, 9])
        self.assertFalse(applied.ask_child_ages)

    def test_younger_and_older_point_at_the_child(self):
        kids = record(adults=2, children=2, child_ages=[7, 11])

        self.assertEqual(
            self.correct(kids, which="younger", to_age=6).record["child_ages"], [6, 11]
        )
        self.assertEqual(self.correct(kids, which="older", to_age=12).record["child_ages"], [7, 12])

    def test_one_child_needs_no_pointing(self):
        one = record(adults=2, children=1, child_ages=[4])

        self.assertEqual(self.correct(one, to_age=5).record["child_ages"], [5])

    def test_nothing_that_says_which_child_is_a_question_and_changes_nothing(self):
        applied = self.correct(to_age=9)

        self.assertEqual([i.code for i in applied.issues], ["ambiguous_age_correction"])
        self.assertEqual(applied.record["child_ages"], [3, 8])

    def test_an_old_age_no_child_has_is_a_question_too(self):
        applied = self.correct(from_age=6, to_age=9)

        self.assertEqual([i.code for i in applied.issues], ["ambiguous_age_correction"])

    def test_the_adults_and_the_other_child_are_untouched(self):
        applied = self.correct(from_age=3, to_age=4)

        self.assertEqual(
            (applied.record["adults"], applied.record["children"], applied.record["child_ages"]),
            (2, 2, [4, 8]),
        )

    def test_a_correction_to_18_or_over_makes_that_one_an_adult(self):
        kids = record(adults=2, children=2, child_ages=[3, 15])

        applied = self.correct(kids, from_age=15, to_age=19)

        self.assertEqual(
            (applied.record["adults"], applied.record["children"], applied.record["child_ages"]),
            (3, 1, [3]),
        )

    def test_with_the_ages_not_all_known_it_is_just_an_age(self):
        partial = record(adults=2, children=2, child_ages=[3])

        applied = self.correct(partial, to_age=8)

        self.assertEqual(applied.record["child_ages"], [3, 8])


class PartyWholeTurnTests(_TripCase):
    def test_two_of_them_are_children_through_the_turns(self):
        provider = ScriptedProvider(
            [
                turn(
                    spain(
                        is_accommodation_request=True,
                        accommodation_place_name="Barcelona",
                        selected_destination_name="Barcelona",
                    ),
                    trip_details={**WHEN, "adults": 5},
                ),
                plain(children=2, children_among_counted=True),
                plain(child_ages=[6, 10]),
            ]
        )
        self.say(provider, "Barcelona dia 5, 3 dias, somos 5")

        asked, _, _ = self.say(provider, "dois deles são crianças")
        self.assertEqual((self.stored()["adults"], self.stored()["children"]), (3, 2))
        self.assertFalse(self.has_search(asked))

        ready, _, _ = self.say(provider, "têm 6 e 10 anos")
        query = dict(query_of(self.url_of(ready)))
        self.assertEqual(query["group_adults"], "3")
        self.assertEqual(query["group_children"], "2")
