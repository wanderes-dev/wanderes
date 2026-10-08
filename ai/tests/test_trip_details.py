"""The trip-details resolver, merge rules and formatters, with no model and no
database: dates are computed against an explicit `today`, and the Booking
kwargs, the caption and the reply's facts are all read from one ResolvedTrip."""

from datetime import date, timedelta

from django.test import SimpleTestCase

from ai.trip_details import (
    EMPTY_RECORD,
    MAX_STAY_LENGTH,
    ResolvedTrip,
    TripTurn,
    apply_components,
    fact_block,
    guard_components,
    has_trip_detail_cues,
    names_detail,
    names_unsupported_filter,
    needs_occupancy,
    previous_question_for_extraction,
    resolve,
    restrict_clears,
    validate_components,
    with_party_offer,
)

TODAY = date(2026, 10, 7)


def comps(
    *,
    day=None,
    month=None,
    year=None,
    relative=None,
    end_day=None,
    end_month=None,
    length=None,
    unit=None,
    adults=None,
    children=None,
    ages=(),
    rooms=None,
    confirms=False,
    cleared=(),
):
    return validate_components(
        {
            "start": {"day": day, "month": month, "year": year, "relative_month": relative},
            "end": {"day": end_day, "month": end_month},
            "stay_length": length,
            "stay_unit": unit,
            "adults": adults,
            "children": children,
            "child_ages": list(ages),
            "rooms": rooms,
            "confirms_party_offer": confirms,
            "cleared_fields": list(cleared),
        }
    )


def apply(current=None, *, today=TODAY, **kwargs):
    return apply_components(current, comps(**kwargs), today)


def record(**fields):
    return {**EMPTY_RECORD, **fields}


class StartDateTests(SimpleTestCase):
    def test_a_bare_day_is_the_next_time_that_day_comes_round_and_says_it_assumed_the_month(self):
        # Said on the 7th: "dia 5" has gone by this month, so it is next month's.
        applied = apply(day=5)

        self.assertEqual(applied.record["start_date"], "2026-11-05")
        self.assertTrue(applied.record["start_assumed_month"])
        self.assertEqual(applied.issues, ())

    def test_a_bare_day_that_is_today_or_later_stays_in_this_month(self):
        self.assertEqual(apply(day=7).record["start_date"], "2026-10-07")
        self.assertEqual(apply(day=20).record["start_date"], "2026-10-20")

    def test_a_bare_day_correcting_a_start_that_is_still_ahead_keeps_its_month(self):
        known = apply(day=5).record  # 5 Nov, the month assumed

        corrected = apply(known, day=8)
        earlier = apply(known, day=3)

        self.assertEqual(corrected.record["start_date"], "2026-11-08")
        self.assertTrue(corrected.record["start_assumed_month"])  # still an assumption
        self.assertEqual(earlier.record["start_date"], "2026-11-03")

    def test_a_correction_keeps_a_month_the_traveler_named_as_named(self):
        known = apply(day=5, month=11).record

        corrected = apply(known, day=8)

        self.assertEqual(corrected.record["start_date"], "2026-11-08")
        self.assertFalse(corrected.record["start_assumed_month"])

    def test_a_bare_day_with_no_start_ahead_to_correct_is_the_next_occurrence(self):
        gone_by = record(start_date="2026-10-01", stay_length=3, stay_unit="days")

        self.assertEqual(apply(day=8).record["start_date"], "2026-10-08")
        self.assertEqual(apply(gone_by, day=8).record["start_date"], "2026-10-08")

    def test_a_correction_to_a_day_the_month_does_not_have_falls_back_to_the_next_occurrence(self):
        known = apply(day=5, month=11).record

        self.assertEqual(apply(known, day=31).record["start_date"], "2026-10-31")

    def test_a_bare_day_skips_months_that_do_not_have_it(self):
        applied = apply(day=31, today=date(2026, 11, 10))  # November has 30 days

        self.assertEqual(applied.record["start_date"], "2026-12-31")

    def test_this_month_that_has_already_passed_is_a_problem_not_next_month(self):
        applied = apply(day=5, relative="this")

        self.assertIsNone(applied.record)
        self.assertFalse(applied.changed)
        self.assertEqual([i.code for i in applied.issues], ["start_in_past"])
        self.assertEqual(applied.issues[0].when, date(2026, 10, 5))

    def test_this_month_still_ahead_is_used_without_assuming_anything(self):
        applied = apply(day=20, relative="this")

        self.assertEqual(applied.record["start_date"], "2026-10-20")
        self.assertFalse(applied.record["start_assumed_month"])

    def test_next_month_including_the_year_rollover(self):
        self.assertEqual(apply(day=5, relative="next").record["start_date"], "2026-11-05")
        self.assertEqual(
            apply(day=5, relative="next", today=date(2026, 12, 10)).record["start_date"],
            "2027-01-05",
        )

    def test_a_named_month_without_a_year_is_its_next_occurrence(self):
        self.assertEqual(apply(day=5, month=11).record["start_date"], "2026-11-05")
        self.assertEqual(apply(day=5, month=3).record["start_date"], "2027-03-05")
        self.assertFalse(apply(day=5, month=11).record["start_assumed_month"])

    def test_an_explicit_year_is_taken_exactly_and_a_past_one_is_refused(self):
        self.assertEqual(apply(day=5, month=3, year=2027).record["start_date"], "2027-03-05")

        past = apply(day=5, month=3, year=2026)

        self.assertIsNone(past.record)
        self.assertEqual(past.issues[0].code, "start_in_past")

    def test_a_date_that_does_not_exist_is_refused(self):
        applied = apply(day=30, month=2)

        self.assertIsNone(applied.record)
        self.assertEqual(applied.issues[0].code, "invalid_date")

    def test_a_month_with_no_day_places_nothing_on_the_calendar(self):
        applied = apply(month=11)

        self.assertIsNone(applied.record)
        self.assertEqual(applied.issues, ())


class StayAndCheckoutTests(SimpleTestCase):
    def test_days_and_nights_both_become_that_many_nights_and_the_unit_is_kept(self):
        days = apply(day=5, length=3, unit="days").record
        nights = apply(day=5, length=3, unit="nights").record

        self.assertEqual((days["stay_length"], days["stay_unit"]), (3, "days"))
        self.assertEqual((nights["stay_length"], nights["stay_unit"]), (3, "nights"))
        for stored in (days, nights):
            trip = resolve(stored, TODAY)
            self.assertEqual(trip.check_in, date(2026, 11, 5))
            self.assertEqual(trip.check_out, date(2026, 11, 8))
            self.assertEqual(trip.nights, 3)

    def test_a_length_with_no_unit_is_read_as_days(self):
        self.assertEqual(apply(length=4).record["stay_unit"], "days")

    def test_a_stay_with_no_start_never_produces_dates(self):
        trip = resolve(apply(length=10, unit="days").record, TODAY)

        self.assertFalse(trip.has_dates)
        self.assertEqual(trip.nights, 10)
        self.assertNotIn("check_in", trip.booking_kwargs())
        self.assertNotIn("check_out", trip.booking_kwargs())

    def test_a_start_with_no_stay_never_produces_dates_either(self):
        trip = resolve(apply(day=5).record, TODAY)

        self.assertFalse(trip.has_dates)
        self.assertEqual(trip.booking_kwargs(), {})

    def test_check_in_and_check_out_are_always_both_or_neither(self):
        records = [
            None,
            apply(day=5).record,
            apply(length=3, unit="days").record,
            apply(day=5, length=3, unit="days").record,
            apply(day=5, length=45, unit="nights").record,
            record(start_date="2026-10-01", stay_length=3, stay_unit="days"),
        ]
        for stored in records:
            with self.subTest(record=stored):
                kwargs = resolve(stored, TODAY).booking_kwargs()
                self.assertEqual("check_in" in kwargs, "check_out" in kwargs)

    def test_an_explicit_range_becomes_a_start_and_a_number_of_nights(self):
        applied = apply(day=5, end_day=8)

        self.assertEqual(applied.record["start_date"], "2026-11-05")
        self.assertEqual(
            (applied.record["stay_length"], applied.record["stay_unit"]), (3, "nights")
        )

    def test_a_range_can_cross_into_the_next_month(self):
        applied = apply(day=28, end_day=3)  # from the 28th to the 3rd

        self.assertEqual(applied.record["start_date"], "2026-10-28")
        self.assertEqual(applied.record["stay_length"], 6)

    def test_a_range_with_its_months_named(self):
        applied = apply(day=5, month=11, end_day=8, end_month=11)
        crossing = apply(day=28, month=12, end_day=3, end_month=1)

        self.assertEqual(applied.record["stay_length"], 3)
        self.assertEqual(crossing.record["start_date"], "2026-12-28")
        self.assertEqual(crossing.record["stay_length"], 6)  # into January 2027

    def test_a_range_that_ends_before_it_starts_is_refused_not_stretched_a_year(self):
        applied = apply(day=5, month=11, end_day=3, end_month=11)

        self.assertEqual([i.code for i in applied.issues], ["end_not_after_start"])
        self.assertIsNone(applied.record["stay_length"])

    def test_this_and_next_month_win_over_a_month_number_the_model_added(self):
        # The model has no calendar to hand: if it writes a month beside
        # "deste mês", the stated relation to today is what is used.
        self.assertEqual(
            apply(day=20, month=11, relative="this").record["start_date"], "2026-10-20"
        )
        self.assertEqual(apply(day=5, month=3, relative="next").record["start_date"], "2026-11-05")

    def test_a_stated_length_beats_an_end_day_the_model_worked_out(self):
        # "15 de julho por uma semana": the model once also reported an end day
        # (the 21st). The length the traveler actually said is what counts.
        applied = apply(day=15, month=7, length=7, unit="days", end_day=21)

        self.assertEqual((applied.record["stay_length"], applied.record["stay_unit"]), (7, "days"))
        self.assertEqual(applied.issues, ())
        self.assertEqual(resolve(applied.record, TODAY).check_out, date(2027, 7, 22))

    def test_a_range_end_alone_uses_the_start_already_known(self):
        known = apply(day=5, length=2, unit="nights").record

        applied = apply(known, end_day=9)

        self.assertEqual(applied.record["start_date"], "2026-11-05")
        self.assertEqual(
            (applied.record["stay_length"], applied.record["stay_unit"]), (4, "nights")
        )

    def test_a_range_end_with_no_start_anywhere_is_ignored(self):
        self.assertIsNone(apply(end_day=8).record)

    def test_a_long_stay_is_not_rejected_for_being_long(self):
        # Nothing here knows what Booking accepts, so nothing here refuses a
        # legitimate long stay: it goes to the link as the traveler said it.
        for nights in (30, 31, 45, 90, MAX_STAY_LENGTH):
            with self.subTest(nights=nights):
                for unit in ("nights", "days"):
                    trip = resolve(apply(day=5, length=nights, unit=unit).record, TODAY)

                    self.assertTrue(trip.has_dates)
                    self.assertEqual(trip.nights, nights)
                    self.assertEqual(trip.check_out, date(2026, 11, 5) + timedelta(days=nights))
                    self.assertEqual(trip.booking_kwargs()["check_out"], trip.check_out)
                caption = trip.caption("Barcelona")
                self.assertIn(f"({nights} nights)", caption)
                self.assertNotIn("longer than", caption)
                self.assertNotIn("longer than", fact_block(TripTurn(trip=trip, today=TODAY)))

    def test_only_an_obviously_pathological_length_is_refused(self):
        for length in (MAX_STAY_LENGTH + 1, 1000):
            with self.subTest(length=length):
                applied = apply(day=5, length=length, unit="nights")

                self.assertIsNone(applied.record["stay_length"])  # unknown, not a Booking rule
                self.assertFalse(resolve(applied.record, TODAY).has_dates)

    def test_a_start_that_has_gone_by_since_it_was_stored_drops_the_dates(self):
        stored = record(start_date="2026-10-05", stay_length=3, stay_unit="days")

        trip = resolve(stored, TODAY)

        self.assertTrue(trip.start_date_past)
        self.assertFalse(trip.has_dates)
        self.assertEqual(trip.booking_kwargs(), {})


class CorrectionAndClearTests(SimpleTestCase):
    def setUp(self):
        self.stored = apply(day=5, length=3, unit="days").record

    def test_a_corrected_start_keeps_the_stay_and_moves_the_checkout(self):
        applied = apply(self.stored, day=6)
        trip = resolve(applied.record, TODAY)

        self.assertTrue(applied.changed)
        self.assertEqual((trip.check_in, trip.check_out), (date(2026, 11, 6), date(2026, 11, 9)))
        self.assertEqual(applied.record["stay_length"], 3)

    def test_a_corrected_length_keeps_the_start_and_moves_the_checkout(self):
        applied = apply(self.stored, length=4, unit="nights")
        trip = resolve(applied.record, TODAY)

        self.assertEqual((trip.check_in, trip.check_out), (date(2026, 11, 5), date(2026, 11, 9)))
        self.assertEqual(applied.record["stay_unit"], "nights")

    def test_nothing_new_changes_nothing(self):
        applied = apply(self.stored)

        self.assertFalse(applied.changed)
        self.assertEqual(applied.record, self.stored)

    def test_a_refused_correction_leaves_the_known_date_alone(self):
        applied = apply(self.stored, day=5, relative="this")  # already passed

        self.assertEqual(applied.record, self.stored)
        self.assertFalse(applied.changed)
        self.assertEqual(applied.issues[0].code, "start_in_past")

    def test_clearing_the_start_or_the_stay_clears_only_that(self):
        no_start = apply(self.stored, cleared=["start"])
        no_stay = apply(self.stored, cleared=["stay"])

        self.assertIsNone(no_start.record["start_date"])
        self.assertFalse(no_start.record["start_assumed_month"])
        self.assertEqual(no_start.record["stay_length"], 3)
        self.assertIsNone(no_stay.record["stay_length"])
        self.assertEqual(no_stay.record["start_date"], "2026-11-05")

    def test_clearing_everything_leaves_no_record(self):
        applied = apply(self.stored, cleared=["start", "stay"])

        self.assertIsNone(applied.record)
        self.assertTrue(applied.changed)

    def test_a_new_value_with_its_clear_flag_is_a_correction_not_a_clear(self):
        applied = apply(self.stored, day=6, cleared=["start"])

        # The flag drops the old start first, then the new one is set.
        self.assertEqual(applied.record["start_date"], "2026-11-06")


class OccupancyTests(SimpleTestCase):
    def test_adults_and_children_are_kept_apart_and_never_summed(self):
        applied = apply(adults=3, children=1)

        self.assertEqual((applied.record["adults"], applied.record["children"]), (3, 1))
        self.assertIsNone(applied.record["child_ages"])

    def test_a_child_with_no_age_is_known_but_left_out_of_the_booking_search(self):
        trip = resolve(apply(adults=3, children=1).record, TODAY)

        self.assertEqual(trip.booking_kwargs(), {"adults": 3})
        self.assertTrue(trip.children_pending)
        self.assertNotIn("group_adults=4", str(trip.booking_kwargs()))

    def test_the_age_asked_for_once_when_a_child_is_first_mentioned(self):
        first = apply(adults=3, children=1)
        again = apply(first.record, adults=3, children=1)
        unrelated = apply(first.record, length=3, unit="days")

        self.assertTrue(first.ask_child_ages)
        self.assertFalse(again.ask_child_ages)
        self.assertFalse(unrelated.ask_child_ages)

    def test_the_age_arrives_in_a_later_message(self):
        waiting = apply(adults=3, children=1).record

        answered = apply(waiting, ages=[5])
        trip = resolve(answered.record, TODAY)

        self.assertEqual(answered.record["child_ages"], [5])
        self.assertFalse(answered.ask_child_ages)
        self.assertEqual(trip.booking_kwargs(), {"adults": 3, "children": 1, "child_ages": [5]})

    def test_the_count_and_the_age_in_one_message_need_no_question(self):
        applied = apply(adults=3, children=1, ages=[5])

        self.assertFalse(applied.ask_child_ages)
        self.assertEqual(resolve(applied.record, TODAY).booking_kwargs()["child_ages"], [5])

    def test_several_children_need_every_age_before_any_of_them_is_sent(self):
        two = apply(adults=2, children=2).record

        first_age = apply(two, ages=[5])
        both = apply(first_age.record, ages=[7])

        self.assertEqual(first_age.record["child_ages"], [5])
        self.assertTrue(first_age.ask_child_ages)  # still waiting on the other one
        self.assertEqual(resolve(first_age.record, TODAY).booking_kwargs(), {"adults": 2})
        self.assertEqual(both.record["child_ages"], [5, 7])
        self.assertEqual(
            resolve(both.record, TODAY).booking_kwargs(),
            {"adults": 2, "children": 2, "child_ages": [5, 7]},
        )

    def test_a_full_set_of_ages_replaces_the_old_ones(self):
        known = apply(adults=2, children=2, ages=[5, 7]).record

        applied = apply(known, ages=[6, 8])

        self.assertEqual(applied.record["child_ages"], [6, 8])

    def test_a_changed_number_of_children_forgets_ages_that_were_for_a_different_group(self):
        known = apply(adults=2, children=1, ages=[5]).record

        applied = apply(known, children=2)

        self.assertIsNone(applied.record["child_ages"])
        self.assertEqual(resolve(applied.record, TODAY).booking_kwargs(), {"adults": 2})

    def test_an_answer_about_some_ages_never_shrinks_the_party(self):
        two = apply(adults=2, children=2).record

        # "tem 5 anos" read as "1 child, age 5": it is one age of the two.
        applied = apply(two, children=1, ages=[5])

        self.assertEqual(applied.record["children"], 2)
        self.assertEqual(applied.record["child_ages"], [5])
        self.assertEqual(resolve(applied.record, TODAY).booking_kwargs(), {"adults": 2})

    def test_saying_there_is_only_one_child_with_no_age_still_changes_the_count(self):
        two = apply(adults=2, children=2).record

        applied = apply(two, children=1)

        self.assertEqual(applied.record["children"], 1)

    def test_ages_with_no_child_to_attach_them_to_are_ignored(self):
        self.assertIsNone(apply(ages=[5]).record)

    def test_someone_eighteen_or_over_is_an_adult_not_a_child(self):
        known = apply(adults=3, children=1).record

        applied = apply(known, ages=[20])

        self.assertEqual((applied.record["adults"], applied.record["children"]), (4, 0))
        self.assertIsNone(applied.record["child_ages"])
        self.assertEqual(resolve(applied.record, TODAY).booking_kwargs(), {"adults": 4})

    def test_a_bare_total_is_adults_with_the_children_left_unknown(self):
        trip = resolve(apply(adults=4).record, TODAY)

        self.assertEqual(trip.booking_kwargs(), {"adults": 4})
        self.assertIsNone(trip.children)

    def test_no_children_stated_is_not_sent_either(self):
        trip = resolve(apply(adults=2, children=0).record, TODAY)

        self.assertEqual(trip.booking_kwargs(), {"adults": 2})

    def test_children_are_never_sent_without_adults(self):
        trip = resolve(apply(children=1, ages=[5]).record, TODAY)

        self.assertTrue(trip.children_complete)
        self.assertEqual(trip.booking_kwargs(), {})

    def test_clearing_children_or_adults(self):
        known = apply(adults=3, children=1, ages=[5]).record

        self.assertIsNone(apply(known, cleared=["children"]).record["children"])
        self.assertIsNone(apply(known, cleared=["children"]).record["child_ages"])
        self.assertIsNone(apply(known, cleared=["adults"]).record["adults"])
        self.assertIsNone(apply(known, cleared=["child_ages"]).record["child_ages"])
        self.assertEqual(apply(known, cleared=["child_ages"]).record["children"], 1)

    def test_a_number_that_is_not_a_traveler_count_never_becomes_one(self):
        # "dia 5 deste mês, ficar 3 noites": the digits are a day and a length.
        applied = apply(day=5, relative="next", length=3, unit="nights")

        self.assertIsNone(applied.record["adults"])
        self.assertTrue(needs_occupancy(applied.record))

    def test_occupancy_is_needed_until_adults_are_known(self):
        self.assertTrue(needs_occupancy(None))
        self.assertTrue(needs_occupancy(apply(length=3).record))
        self.assertFalse(needs_occupancy(apply(adults=1).record))


class ValidationTests(SimpleTestCase):
    def test_out_of_range_or_malformed_values_become_unknown(self):
        parsed = comps(day=40, month=13, adults=0, children=-1, length=0, relative="soon")

        self.assertEqual(
            parsed["start"], {"day": None, "month": None, "year": None, "relative_month": None}
        )
        self.assertIsNone(parsed["adults"])
        self.assertIsNone(parsed["children"])
        self.assertIsNone(parsed["stay_length"])
        self.assertIsNone(parsed["stay_unit"])

    def test_garbage_in_gives_all_unknown(self):
        for raw in (None, "text", [], {"start": "x", "child_ages": "no", "cleared_fields": 3}):
            with self.subTest(raw=raw):
                parsed = validate_components(raw)
                self.assertIsNone(apply_components(None, parsed, TODAY).record)

    def test_a_damaged_stored_record_reads_as_unknown(self):
        trip = resolve(
            {
                "start_date": "not-a-date",
                "stay_length": "3",
                "stay_unit": "fortnights",
                "adults": True,
                "children": 1,
                "child_ages": [5, 6],  # more ages than children
            },
            TODAY,
        )

        self.assertEqual(trip, ResolvedTrip(children=1))
        self.assertEqual(resolve("nope", TODAY), ResolvedTrip())


class CueGateTests(SimpleTestCase):
    def test_messages_that_give_trip_details_wake_the_call(self):
        for message in (
            "quero ir dia 5 ficar 3 dias",
            "3 adultos e uma criança",
            "5 anos",
            "somos eu e minha esposa",
            "de 5 a 8 de novembro",
            "ficar três noites",
            "we are two adults and a kid",
            "viajo sozinho",
            "quero um quarto",
            "quero dois quartos por favor",
            "I need two rooms",
            "ainda não sei as datas",
            "esquece a duração",
            "dia 05",
            "por que vc presumiu 4 pessoas?",
        ):
            with self.subTest(message=message):
                self.assertTrue(has_trip_detail_cues(message))

    def test_ordinary_conversation_does_not(self):
        for message in (
            "o que fazer lá?",
            "obrigado",
            "quanto custa?",
            "conte-me mais sobre Barcelona",
            "e hospedagem?",
            "quero hospedagens",
            "me ajuda a montar um roteiro?",
            "what is the food like there?",
            "qual a moeda de lá?",
        ):
            with self.subTest(message=message):
                self.assertFalse(has_trip_detail_cues(message))


class ClearGuardTests(SimpleTestCase):
    def test_a_complaint_about_the_date_clears_the_date_and_nothing_else(self):
        parsed = comps(cleared=["start", "stay", "adults", "children"])

        kept = restrict_clears(parsed, "continua com a data errada")

        self.assertEqual(kept["cleared_fields"], ["start"])

    def test_each_clear_needs_a_word_that_names_its_detail(self):
        parsed = comps(cleared=["start", "stay", "adults", "children", "child_ages"])

        self.assertEqual(
            restrict_clears(parsed, "esquece a duração e o número de pessoas")["cleared_fields"],
            ["stay", "adults"],
        )
        self.assertEqual(
            restrict_clears(parsed, "sem crianças afinal")["cleared_fields"],
            ["children", "child_ages"],
        )
        self.assertEqual(restrict_clears(parsed, "forget the dates")["cleared_fields"], ["start"])

    def test_a_phrasing_it_does_not_recognise_clears_nothing(self):
        parsed = comps(cleared=["start", "adults"])

        self.assertEqual(restrict_clears(parsed, "vergiss das")["cleared_fields"], [])

    def test_nothing_to_restrict_is_returned_untouched(self):
        parsed = comps(adults=2)

        self.assertIs(restrict_clears(parsed, "somos 2"), parsed)


class RoomsTests(SimpleTestCase):
    def test_rooms_are_set_on_their_own_and_never_touch_the_party(self):
        known = apply(adults=3, children=1, ages=[5]).record

        applied = apply(known, rooms=2)

        self.assertEqual(applied.record["rooms"], 2)
        self.assertEqual(
            (applied.record["adults"], applied.record["children"], applied.record["child_ages"]),
            (3, 1, [5]),
        )
        self.assertTrue(applied.rooms_changed)

    def test_a_correction_changes_only_the_rooms_and_keeps_dates_and_occupancy(self):
        known = apply(day=5, length=3, unit="days", adults=3, children=1, ages=[5], rooms=2).record

        corrected = apply(known, rooms=1)

        self.assertEqual(corrected.record["rooms"], 1)
        self.assertEqual(
            {k: v for k, v in corrected.record.items() if k != "rooms"},
            {k: v for k, v in known.items() if k != "rooms"},
        )

    def test_clearing_the_rooms_clears_only_the_rooms(self):
        known = apply(day=5, length=3, unit="days", adults=3, rooms=2).record

        cleared = apply(known, cleared=["rooms"])

        self.assertIsNone(cleared.record["rooms"])
        self.assertEqual(cleared.record["adults"], 3)
        self.assertEqual(cleared.record["start_date"], "2026-11-05")
        self.assertTrue(cleared.rooms_changed)

    def test_repeating_the_same_rooms_changes_nothing(self):
        known = apply(adults=3, rooms=2).record

        again = apply(known, rooms=2)

        self.assertFalse(again.changed)
        self.assertFalse(again.rooms_changed)

    def test_rooms_that_fit_the_adults_go_into_the_search(self):
        for adults, rooms in ((3, 2), (2, 2), (4, 1)):
            with self.subTest(adults=adults, rooms=rooms):
                trip = resolve(apply(adults=adults, rooms=rooms).record, TODAY)

                self.assertTrue(trip.rooms_in_search)
                self.assertEqual(trip.booking_kwargs()["rooms"], rooms)
                self.assertEqual(trip.link_summary()["rooms"], rooms)

    def test_more_rooms_than_adults_are_kept_but_never_claimed_or_sent(self):
        # Booking silently uses at most one room per adult, so a caption or link
        # saying 3 rooms for 1 adult would be false.
        record = apply(adults=1, rooms=3).record

        trip = resolve(record, TODAY)

        self.assertEqual(record["rooms"], 3)  # what the traveler asked for stays on record
        self.assertTrue(trip.rooms_conflict)
        self.assertFalse(trip.rooms_in_search)
        self.assertNotIn("rooms", trip.booking_kwargs())
        self.assertIsNone(trip.link_summary()["rooms"])
        self.assertIn(
            "3 rooms not included - Booking needs an adult in every room", trip.caption("Barcelona")
        )
        facts = fact_block(TripTurn(trip=trip, ask_rooms=True, today=TODAY))
        self.assertIn("the rooms are NOT in the Booking search", facts)
        self.assertIn("Never say the rooms were set", facts)
        self.assertIn(
            "whether to change the number of adults or use fewer rooms (at most 1)", facts
        )

    def test_fixing_the_conflict_by_either_side_makes_the_rooms_representable(self):
        record = apply(adults=1, rooms=3).record

        fewer_rooms = resolve(apply(record, rooms=1).record, TODAY)
        more_adults = resolve(apply(record, adults=3).record, TODAY)

        self.assertEqual(fewer_rooms.booking_kwargs()["rooms"], 1)
        self.assertEqual(more_adults.booking_kwargs()["rooms"], 3)

    def test_rooms_with_nobody_known_to_sleep_in_them_are_noted_not_sent(self):
        trip = resolve(apply(rooms=2).record, TODAY)

        self.assertEqual(trip.booking_kwargs(), {})
        self.assertIn(
            "2 rooms not included yet - the number of adults is needed", trip.caption("Barcelona")
        )
        self.assertIn(
            "Rooms: 2 (noted), not in the search until the number of adults is known",
            fact_block(TripTurn(trip=trip, today=TODAY)),
        )

    def test_the_rooms_are_bounded_like_every_other_count(self):
        for rooms in (0, -1, 11, 100):
            with self.subTest(rooms=rooms):
                self.assertIsNone(comps(rooms=rooms)["rooms"])
        self.assertEqual(comps(rooms=10)["rooms"], 10)

    def test_the_caption_of_the_finished_conversation_has_the_rooms(self):
        trip = _trip(
            start_date="2026-11-05",
            start_assumed_month=True,
            stay_length=3,
            stay_unit="days",
            adults=3,
            children=1,
            child_ages=[5],
            rooms=2,
        )

        self.assertEqual(
            trip.caption("Barcelona"),
            "Booking search: Barcelona · 5 Nov 2026 – 8 Nov 2026 (3 nights), month assumed"
            " · 3 adults · 1 child (age 5) · 2 rooms",
        )
        self.assertEqual(
            trip.booking_kwargs(),
            {
                "check_in": date(2026, 11, 5),
                "check_out": date(2026, 11, 8),
                "adults": 3,
                "children": 1,
                "child_ages": [5],
                "rooms": 2,
            },
        )

    def test_the_rooms_conflict_is_asked_only_when_this_message_is_about_the_rooms(self):
        # (the orchestration decides; this is the vocabulary it uses)
        self.assertTrue(names_detail("quero dois quartos por favor", "rooms"))
        self.assertTrue(names_detail("I need two rooms", "rooms"))
        self.assertFalse(names_detail("somos 3 adultos", "rooms"))

    def test_a_turn_with_something_to_ask_says_so(self):
        trip = resolve(apply(adults=1, rooms=3).record, TODAY)

        self.assertFalse(TripTurn(trip=trip, today=TODAY).must_ask)
        self.assertTrue(TripTurn(trip=trip, ask_rooms=True, today=TODAY).must_ask)
        self.assertTrue(TripTurn(trip=trip, ask_child_ages=True, today=TODAY).must_ask)
        past = apply(day=5, relative="this")
        self.assertTrue(TripTurn(trip=trip, issues=past.issues, today=TODAY).must_ask)


class UnsupportedFilterVocabularyTests(SimpleTestCase):
    def test_a_price_level_star_rating_or_amenity_is_a_filter_the_search_cannot_apply(self):
        for message in (
            "quero hotel barato",
            "something cheap please",
            "um hotel de luxo",
            "hotel caro",
            "hotel de 4 estrelas",
            "a five star hotel",
            "com piscina",
            "pet friendly",
        ):
            with self.subTest(message=message):
                self.assertTrue(names_unsupported_filter(message))

    def test_ordinary_requests_and_cost_questions_are_not(self):
        for message in (
            "quero hospedagens",
            "quanto custa?",
            "qual o preço da passagem?",
            "quero dois quartos por favor",
            "qual bairro é melhor para ficar?",
            "cara, quero hospedagens",
        ):
            with self.subTest(message=message):
                self.assertFalse(names_unsupported_filter(message))


class ComponentGuardTests(SimpleTestCase):
    def guarded(self, current, message, **kwargs):
        return apply_components(current, guard_components(comps(**kwargs), message), TODAY)

    def test_a_message_about_rooms_cannot_change_who_is_going(self):
        known = apply(adults=3, children=1, ages=[5]).record

        for message in (
            "quero dois quartos por favor",
            "quero uma pesquisa para dois quartos",
            "two rooms please",
        ):
            with self.subTest(message=message):
                applied = self.guarded(known, message, adults=2, children=2, ages=[7, 8], rooms=2)

                self.assertEqual(applied.record["rooms"], 2)
                self.assertEqual(
                    (
                        applied.record["adults"],
                        applied.record["children"],
                        applied.record["child_ages"],
                    ),
                    (3, 1, [5]),
                )

    def test_rooms_said_together_with_the_party_keep_the_party(self):
        applied = self.guarded(None, "2 adultos e 2 quartos", adults=2, rooms=2)

        self.assertEqual((applied.record["adults"], applied.record["rooms"]), (2, 2))

    def test_a_stray_age_of_zero_does_not_replace_a_known_age(self):
        known = apply(adults=3, children=1, ages=[5]).record

        applied = self.guarded(known, "quero dois quartos por favor", ages=[0], rooms=2)

        self.assertEqual(applied.record["child_ages"], [5])
        self.assertEqual(resolve(applied.record, TODAY).booking_kwargs()["child_ages"], [5])

    def test_a_stray_age_of_zero_beside_other_details_does_not_replace_the_known_age(self):
        # No rooms in these, so it is the age guard alone that holds the 5.
        known = apply(adults=3, children=1, ages=[5]).record

        for message in ("somos 3 adultos e uma criança", "quero ir dia 05", "ok, pode ser"):
            with self.subTest(message=message):
                applied = self.guarded(known, message, ages=[0])

                self.assertEqual(applied.record["child_ages"], [5])

    def test_an_explicit_correction_to_age_zero_is_honored(self):
        known = apply(adults=3, children=1, ages=[5]).record

        for message in (
            "na verdade ela tem 0 anos",
            "é um bebê de 8 meses",
            "actually she is 0 years old",
        ):
            with self.subTest(message=message):
                applied = self.guarded(known, message, ages=[0])

                self.assertEqual(applied.record["child_ages"], [0])

    def test_an_infant_is_a_legitimate_first_age(self):
        applied = self.guarded(apply(adults=2, children=1).record, "um bebê, 3 meses", ages=[0])

        self.assertEqual(applied.record["child_ages"], [0])

    def test_age_zero_is_not_rejected_globally_only_unbacked(self):
        # A positive age is never touched by the guard.
        applied = self.guarded(apply(adults=2, children=1).record, "ela tem 5 anos", ages=[5])

        self.assertEqual(applied.record["child_ages"], [5])


class PreviousQuestionTests(SimpleTestCase):
    HISTORY = [
        {"role": "user", "content": "quero hospedagens"},
        {"role": "assistant", "content": "Quantas pessoas vão? Antes eu falei de 4 pessoas."},
    ]

    def test_a_short_reply_gets_the_assistants_last_message_with_every_digit_masked(self):
        question = previous_question_for_extraction(self.HISTORY, "5 anos")

        self.assertIn("Quantas pessoas vão?", question)
        self.assertNotIn("4", question)
        self.assertIn("#", question)

    def test_a_message_that_stands_alone_gets_no_question(self):
        long_message = "quero ir em novembro, no dia cinco, e ficar três noites em Barcelona"

        self.assertIsNone(previous_question_for_extraction(self.HISTORY, long_message))

    def test_no_assistant_message_means_no_question(self):
        self.assertIsNone(previous_question_for_extraction([], "5 anos"))
        self.assertIsNone(previous_question_for_extraction(self.HISTORY[:1], "5 anos"))

    def test_only_the_tail_of_a_long_reply_is_shown(self):
        history = [{"role": "assistant", "content": "x" * 2000 + " Quantos anos tem a criança?"}]

        question = previous_question_for_extraction(history, "5")

        self.assertLessEqual(len(question), 400)
        self.assertTrue(question.endswith("Quantos anos tem a criança?"))


def _trip(**fields):
    return resolve(record(**fields), TODAY)


class OneObjectDrivesEverythingTests(SimpleTestCase):
    """The URL's kwargs, the caption and the reply's facts are three views of
    the same ResolvedTrip: whatever one says is carried, the others say too."""

    RECORDS = {
        "nothing": None,
        "stay only": record(stay_length=10, stay_unit="days"),
        "dates only": record(start_date="2026-11-05", stay_length=3, stay_unit="days"),
        "dates assumed": record(
            start_date="2026-11-05", start_assumed_month=True, stay_length=3, stay_unit="days"
        ),
        "adults": record(adults=3),
        "child waiting for an age": record(adults=3, children=1),
        "child with an age": record(adults=3, children=1, child_ages=[5]),
        "two children, one age": record(adults=2, children=2, child_ages=[5]),
        "everything": record(
            start_date="2026-11-05",
            start_assumed_month=True,
            stay_length=3,
            stay_unit="nights",
            adults=3,
            children=2,
            child_ages=[5, 7],
        ),
        "start already past": record(start_date="2026-10-01", stay_length=3, stay_unit="days"),
        "long stay": record(start_date="2026-11-05", stay_length=45, stay_unit="days"),
        "children without adults": record(children=1, child_ages=[5]),
        "rooms that fit": record(adults=3, rooms=2),
        "rooms equal to the adults": record(adults=2, rooms=2),
        "more rooms than adults": record(adults=1, rooms=3),
        "rooms, adults unknown": record(rooms=2),
    }

    def test_the_three_renderings_agree_for_every_state(self):
        for name, stored in self.RECORDS.items():
            with self.subTest(state=name):
                trip = resolve(stored, TODAY)
                kwargs = trip.booking_kwargs()
                caption = trip.caption("Barcelona")
                facts = fact_block(TripTurn(trip=trip, today=TODAY), always=True)

                # dates
                self.assertEqual("check_in" in kwargs, "Check-in:" in facts)
                if "check_in" in kwargs:
                    self.assertIn(
                        f"{kwargs['check_in']:%-d %b %Y}".replace("-", ""), caption.replace("-", "")
                    )
                    self.assertIn("Check-in:", facts)
                    if trip.search_ready:  # the summary of what the link carries
                        self.assertIn(kwargs["check_in"].isoformat(), facts)
                        self.assertIn(kwargs["check_out"].isoformat(), facts)
                else:
                    self.assertIn("no dates set", caption)
                # adults
                if "adults" in kwargs:
                    self.assertIn(f"{kwargs['adults']} adult", caption)
                    self.assertIn(f"Adults: {kwargs['adults']}.", facts)
                else:
                    self.assertIn("travelers not set", caption)
                    self.assertIn("Travelers: not stated yet.", facts)
                # children
                self.assertEqual("children" in kwargs, "(age" in caption)
                children_line = next(
                    (ln for ln in facts.splitlines() if ln.startswith("- Children:")), ""
                )
                self.assertEqual("children" in kwargs, "included in the search." in children_line)
                self.assertEqual(
                    trip.children_pending, "not included yet - the age is needed" in caption
                )
                self.assertEqual(
                    trip.children_pending, "NOT included in the Booking search" in facts
                )
                # rooms
                self.assertEqual("rooms" in kwargs, trip.rooms_in_search)
                if "rooms" in kwargs:
                    self.assertIn(f"{kwargs['rooms']} room", caption)
                    self.assertIn(f"Rooms: {kwargs['rooms']} - included in the search.", facts)
                elif trip.rooms is not None:
                    self.assertIn(f"{trip.rooms} rooms not included", caption)
                    self.assertNotIn(
                        "included in the search", facts.split("Rooms:")[1].split("\n")[0]
                    )
                else:
                    self.assertNotIn(
                        "room", caption.replace("rooms", "room").split("Booking search:")[1]
                    )
                # what the search carries - or that there is none yet
                if trip.search_ready:
                    self.assertIn("The Booking search link carries exactly:", facts)
                    self.assertNotIn("NO Booking search action", facts)
                else:
                    self.assertIn("There is NO Booking search action yet", facts)
                    self.assertNotIn("carries exactly", facts)

    def test_the_caption_for_the_finished_conversation(self):
        trip = _trip(
            start_date="2026-11-05",
            start_assumed_month=True,
            stay_length=3,
            stay_unit="days",
            adults=3,
            children=1,
            child_ages=[5],
        )

        self.assertEqual(
            trip.caption("Barcelona"),
            "Booking search: Barcelona · 5 Nov 2026 – 8 Nov 2026 (3 nights), month assumed"
            " · 3 adults · 1 child (age 5)",
        )

    def test_the_caption_says_what_is_known_but_left_out(self):
        self.assertEqual(
            _trip(stay_length=10, stay_unit="days", adults=3, children=1).caption("Barcelona"),
            "Booking search: Barcelona · no dates set (a start date is needed) · 3 adults"
            " · 1 child not included yet - the age is needed",
        )
        self.assertEqual(
            _trip().caption("Barcelona"),
            "Booking search: Barcelona · no dates set · travelers not set",
        )

    def test_the_facts_disclose_the_assumed_month_and_the_days_counted_as_nights(self):
        trip = _trip(
            start_date="2026-11-05",
            start_assumed_month=True,
            stay_length=3,
            stay_unit="days",
            adults=2,
        )

        facts = fact_block(TripTurn(trip=trip, today=TODAY))

        self.assertIn("Check-in: Thursday 5 November 2026.", facts)
        self.assertIn("the month was assumed", facts)
        self.assertIn("Check-out: Sunday 8 November 2026 (3 nights).", facts)
        self.assertIn('The traveler said "3 days", counted as 3 nights.', facts)
        self.assertIn("carries exactly: dates 2026-11-05 to 2026-11-08, 2 adults", facts)

    def test_the_facts_carry_what_this_turn_raised(self):
        applied = apply(day=5, relative="this", adults=3, children=1)
        turn = TripTurn(
            trip=resolve(applied.record, TODAY),
            issues=applied.issues,
            ask_child_ages=applied.ask_child_ages,
            today=TODAY,
        )

        facts = fact_block(turn)

        self.assertIn("Needs clarification:", facts)
        self.assertIn("Monday 5 October 2026, which has already passed", facts)
        self.assertIn("Ask which date they mean.", facts)
        self.assertIn("a child's age is missing - ask for the age", facts)

    def test_an_uninformative_turn_adds_nothing_unless_it_is_a_stays_reply(self):
        turn = TripTurn(trip=ResolvedTrip(), today=TODAY)

        self.assertEqual(fact_block(None), "")
        self.assertEqual(fact_block(turn), "")
        self.assertIn("Dates: none set", fact_block(turn, always=True))


READY = {
    "start_date": "2026-11-05",
    "start_assumed_month": True,
    "stay_length": 3,
    "stay_unit": "days",
    "adults": 2,
}


class SearchReadinessTests(SimpleTestCase):
    """One decision - `missing_for_search` - says whether there is a Booking
    search at all, and what to ask for next, in a fixed order."""

    def test_what_is_missing_comes_back_in_the_order_to_ask_for_it(self):
        cases = (
            (record(), ("check_in", "stay_length", "adults")),
            (record(stay_length=10, stay_unit="days"), ("check_in", "adults")),
            (record(start_date="2026-11-05"), ("stay_length", "adults")),
            (record(adults=2), ("check_in", "stay_length")),
            (record(**{**READY, "adults": None}), ("adults",)),
            (record(**READY), ()),
            (record(**READY, children=1), ("child_ages",)),
            (record(**READY, children=2, child_ages=[5]), ("child_ages",)),
            (record(**READY, children=1, child_ages=[5]), ()),
            (record(**{**READY, "adults": None}, children=1, child_ages=[5]), ("adults",)),
            (record(**{**READY, "adults": 1}, rooms=3), ("rooms",)),
            (record(**READY, rooms=2), ()),
            # the start the traveler gave has already passed: as good as no start
            (record(**{**READY, "start_date": "2026-10-01"}), ("check_in",)),
        )
        for stored, expected in cases:
            with self.subTest(expected=expected, stored=stored):
                self.assertEqual(resolve(stored, TODAY).missing_for_search, expected)

    def test_everything_missing_is_listed_with_the_earliest_first(self):
        stored = record(adults=1, rooms=3, children=1)

        trip = resolve(stored, TODAY)

        self.assertEqual(
            trip.missing_for_search, ("check_in", "stay_length", "child_ages", "rooms")
        )

    def test_the_search_is_ready_exactly_when_nothing_is_missing(self):
        for stored in (record(), record(adults=3), record(**READY, children=1), record(**READY)):
            with self.subTest(stored=stored):
                trip = resolve(stored, TODAY)

                self.assertEqual(trip.search_ready, not trip.missing_for_search)

    def test_an_unready_trip_has_no_search_at_all_not_a_smaller_one(self):
        trip = resolve(record(adults=3), TODAY)

        self.assertIsNone(trip.search_kwargs())
        self.assertEqual(trip.booking_kwargs(), {"adults": 3})  # the formatter itself is unchanged

    def test_a_ready_trip_searches_with_exactly_what_it_holds(self):
        trip = resolve(record(**READY, children=1, child_ages=[5], rooms=2), TODAY)

        self.assertEqual(trip.search_kwargs(), trip.booking_kwargs())
        self.assertEqual(trip.search_kwargs()["rooms"], 2)

    def test_the_start_is_known_even_before_the_length_is(self):
        trip = resolve(record(start_date="2026-11-05"), TODAY)

        self.assertEqual(trip.start_date, date(2026, 11, 5))
        self.assertFalse(trip.has_dates)


class PartyOfferTests(SimpleTestCase):
    """The party size on the traveler's profile is only ever a question. A clear
    "sim" to that question confirms it; nothing else turns it into adults."""

    ASKED = record(**{**READY, "adults": None}, adults_offer=2)

    def test_a_yes_confirms_the_offered_party_as_adults(self):
        applied = apply(self.ASKED, confirms=True)

        self.assertEqual(applied.record["adults"], 2)
        self.assertTrue(applied.details_changed)
        self.assertNotIn("adults_offer", applied.record)

    def test_what_the_traveler_says_about_who_is_going_wins_over_the_offer(self):
        applied = apply(self.ASKED, confirms=True, adults=3)

        self.assertEqual(applied.record["adults"], 3)

    def test_anything_but_a_clear_yes_leaves_the_adults_unknown(self):
        applied = apply(self.ASKED)  # "não", a different topic, silence

        self.assertIsNone(applied.record["adults"])

    def test_a_yes_with_no_question_asked_confirms_nothing(self):
        applied = apply(record(**{**READY, "adults": None}), confirms=True)

        self.assertIsNone(applied.record["adults"])

    def test_a_yes_cannot_survive_the_traveler_taking_the_adults_back(self):
        applied = apply(self.ASKED, confirms=True, cleared=["adults"])

        self.assertIsNone(applied.record["adults"])

    def test_the_offer_is_good_for_one_reply_only(self):
        first = apply(self.ASKED, length=4, unit="days")

        self.assertNotIn("adults_offer", first.record)
        later = apply(first.record, confirms=True)  # a stray "sim" a turn later
        self.assertIsNone(later.record["adults"])

    def test_an_offer_lapsing_is_not_a_change_to_the_trip(self):
        applied = apply(self.ASKED)

        self.assertTrue(applied.changed)  # the record is rewritten without the offer ...
        self.assertFalse(applied.details_changed)  # ... but nothing the search uses moved

    def test_the_offer_never_reaches_the_search(self):
        trip = resolve(self.ASKED, TODAY)

        self.assertIsNone(trip.adults)
        self.assertNotIn("adults", trip.booking_kwargs())
        self.assertEqual(trip.missing_for_search, ("adults",))

    def test_remembering_the_question_keeps_the_rest_of_the_trip(self):
        noted = with_party_offer(record(**{**READY, "adults": None}), 4)

        self.assertEqual(noted["adults_offer"], 4)
        self.assertEqual(noted["stay_length"], 3)
        self.assertIsNone(with_party_offer(None, 999)["adults_offer"])  # out of range: no offer

    def test_a_record_without_a_pending_question_is_stored_as_it_always_was(self):
        applied = apply(None, length=3, unit="days")

        self.assertNotIn("adults_offer", applied.record)
        self.assertIsNone(apply(None).record)


class AskTheNextThingTests(SimpleTestCase):
    """A reply that asks asks for the first thing the search is missing - one
    question - and tells the reply there is no search yet."""

    def turn(self, stored, **fields):
        return TripTurn(trip=resolve(stored, TODAY), today=TODAY, **fields)

    def test_each_step_asks_one_question_in_order(self):
        steps = (
            (record(), "start date is missing"),
            (record(stay_length=10, stay_unit="days"), "start date is missing"),
            (record(start_date="2026-11-05"), "length of the stay is missing"),
            (
                record(start_date="2026-11-05", stay_length=3, stay_unit="days"),
                "nobody has said how many adults are going",
            ),
            (record(**READY, children=1), "a child's age is missing"),
            (record(**{**READY, "adults": 1}, rooms=3), "3 rooms can't go in the search"),
        )
        for stored, expected in steps:
            with self.subTest(expected=expected):
                facts = fact_block(self.turn(stored), ask_missing=True)

                self.assertEqual(facts.count("Needs clarification"), 1)
                self.assertIn(expected, facts)

    def test_it_says_what_the_search_is_waiting_for(self):
        facts = fact_block(self.turn(record(stay_length=10, stay_unit="days")), ask_missing=True)

        self.assertIn("There is NO Booking search action yet", facts)
        self.assertIn("a start date, the number of adults", facts)
        self.assertIn("Never say a search or a link is ready", facts)
        self.assertNotIn("carries exactly", facts)

    def test_a_ready_trip_asks_nothing(self):
        facts = fact_block(self.turn(record(**READY)), ask_missing=True)

        self.assertNotIn("Needs clarification", facts)
        self.assertIn("carries exactly: dates 2026-11-05 to 2026-11-08, 2 adults", facts)

    def test_a_reply_that_is_not_asking_is_not_told_to(self):
        facts = fact_block(self.turn(record(stay_length=10, stay_unit="days")))

        self.assertNotIn("Needs clarification", facts)
        self.assertIn("There is NO Booking search action yet", facts)

    def test_a_reply_that_asks_is_told_the_facts_even_when_nothing_is_known(self):
        self.assertEqual(fact_block(self.turn(None)), "")

        facts = fact_block(self.turn(None), ask_missing=True)

        self.assertIn("start date is missing", facts)

    def test_a_date_that_could_not_be_used_is_the_one_question(self):
        past = apply(day=1, relative="this")
        turn = self.turn(past.record, issues=past.issues)

        facts = fact_block(turn, ask_missing=True)

        self.assertEqual(facts.count("Needs clarification"), 1)
        self.assertIn("already passed", facts)

    def test_the_profiles_party_is_asked_about_when_who_is_going_is_next(self):
        stored = record(start_date="2026-11-05", stay_length=3, stay_unit="days")
        turn = self.turn(stored, profile_party=2)

        facts = fact_block(turn, ask_missing=True)

        self.assertEqual(turn.party_offer, 2)
        self.assertIn("profile says they usually travel with 2 people", facts)
        self.assertIn("whether those 2 people are all adults", facts)
        self.assertIn("do not assume it", facts)
        self.assertNotIn("how many adults are going and whether any children", facts)

    def test_without_a_profile_party_the_question_is_the_plain_one(self):
        stored = record(start_date="2026-11-05", stay_length=3, stay_unit="days")

        facts = fact_block(self.turn(stored), ask_missing=True)

        self.assertIsNone(self.turn(stored).party_offer)
        self.assertIn("how many adults are going and whether any children", facts)
        self.assertNotIn("profile", facts)

    def test_the_profiles_party_is_not_offered_while_something_earlier_is_missing(self):
        for stored in (record(), record(stay_length=10, stay_unit="days"), record(**READY)):
            with self.subTest(stored=stored):
                turn = self.turn(stored, profile_party=2)

                self.assertIsNone(turn.party_offer)
                self.assertNotIn("profile", fact_block(turn, ask_missing=True))

    def test_the_profiles_party_is_not_offered_over_an_unusable_date(self):
        past = apply(day=1, relative="this", length=3, unit="days")

        turn = self.turn(past.record, issues=past.issues, profile_party=2)

        self.assertIsNone(turn.party_offer)
