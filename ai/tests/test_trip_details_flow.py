"""Trip details through whole turns: what the traveler says about dates, length
and who is going becomes one resolved trip that the Booking link, its caption
and the reply's facts all share - with a model call only when there is
something to read, and the existing state-ownership protocol around the
stored record."""

from datetime import date
from unittest import mock
from urllib.parse import parse_qsl, urlparse

from ai import memory
from ai.orchestration import stream_travel_recommendation
from ai.tests.helpers import ScriptedProvider, intent
from ai.tests.test_selected_destination import WHEN, _Case, barcelona_record, spain, turn
from ai.tests.test_state_ownership import _OrchestrationCase
from ai.views import _recommendation_card_data
from evaluations.view_path import ViewSession
from users.models import TravelerProfile

TODAY = date(2026, 10, 7)
_MERGE_PATH_CALLS = ["travel_message", "climate_budget_signal", "traveler_state_clear_signal"]


def stays(place="Barcelona", **trip):
    """A turn the intent call files as a stays request, with the trip
    components the trip-details call returns for it."""
    return turn(
        spain(is_accommodation_request=True, accommodation_place_name=place),
        **({"trip_details": trip} if trip else {}),
    )


def booking(place=None, **trip):
    """A turn the intent call files as a request to book (optionally also a
    stays request for `place`), with the trip components for it."""
    flags = {"is_booking_request": True}
    if place:
        flags.update(is_accommodation_request=True, accommodation_place_name=place)
    return turn(spain(**flags), **({"trip_details": trip} if trip else {}))


def plain(**trip):
    """A turn the intent call files as ordinary conversation."""
    return turn(spain(), **({"trip_details": trip} if trip else {}))


def query_of(url) -> list[tuple[str, str]]:
    return parse_qsl(urlparse(url).query)


class _TripCase(_Case):
    def setUp(self):
        super().setUp()
        patcher = mock.patch("ai.orchestration._today", return_value=TODAY)
        patcher.start()
        self.addCleanup(patcher.stop)

    def card_of(self, result) -> dict:
        return _recommendation_card_data(
            result.recommendations[0], detail_shown=True, trip=result.trip
        )

    def url_of(self, result) -> str:
        return self.card_of(result)["accommodation_search_url"]

    def has_search(self, result) -> bool:
        """Whether the card this turn sends carries a Booking search."""
        return bool(result.recommendations) and "accommodation_search_url" in self.card_of(result)

    def trip_calls(self, provider) -> int:
        return provider.structured_calls.count("trip_details_signal")

    def stored(self):
        return memory.get_climate_budget(self.key)["trip_details"]


class ProductionConversationTests(_TripCase):
    """The conversation that exposed the defect: three adults and a child came
    out as four adults, and no date ever reached the link."""

    def test_the_whole_conversation_from_the_first_message_to_the_final_link(self):
        provider = ScriptedProvider(
            [
                turn(
                    spain(selected_destination_name="Barcelona"),
                    trip_details={"stay_length": 10, "stay_unit": "days"},
                ),
                turn(spain(), trip_details={"start": {"day": 5, "month": 11}}),
                turn(spain(), trip_details={"adults": 3, "children": 1}),
                turn(spain(), trip_details={"child_ages": [5]}),
                turn(spain(), trip_details={"rooms": 2}),
                turn(spain(), trip_details={"cleared_fields": ["start"]}),
            ]
        )

        # "Quero ir pra Barcelona 10 dias" - the place is chosen; there is no
        # search to offer yet, and the reply's closing question is the start date
        chosen, _, _ = self.say(provider, "Quero ir pra Barcelona 10 dias")
        self.assert_detail_of(chosen, "barcelona-es")
        self.assertFalse(self.has_search(chosen))
        self.assertFalse(chosen.retire_stays)  # there was nothing on the page to retire
        prompt = self.prompt_of_last_reply(provider)
        self.assertIn("Stay: 10 days (counted as 10 nights)", prompt)
        self.assertIn("There is NO Booking search action yet", prompt)
        self.assertIn("the trip's start date is missing", prompt)
        self.assertIn("end your reply with that one question", prompt)

        # "Vou dia 5 de novembro" - the date is kept, the 10 nights are kept, and
        # who is going is the next (and only) question
        dated, _, state = self.say(provider, "Vou dia 5 de novembro")
        self.assertEqual(dated.recommendations, [])
        self.assertEqual(state["trip_details"]["start_date"], "2026-11-05")
        self.assertEqual(state["trip_details"]["stay_length"], 10)
        prompt = self.prompt_of_last_reply(provider)
        self.assertIn("nobody has said how many adults are going", prompt)
        self.assertIn("Check-out: Sunday 15 November 2026 (10 nights).", prompt)
        self.assertIn("Never say a search or a link is ready", prompt)
        self.assertFalse(dated.retire_stays)  # no search before, none now

        # "Somos 3 adultos e uma criança" - never four adults; the age is next
        waiting, _, state = self.say(provider, "Somos 3 adultos e uma criança")
        self.assertEqual(waiting.recommendations, [])
        self.assertEqual(
            (state["trip_details"]["adults"], state["trip_details"]["children"]), (3, 1)
        )
        self.assertIsNone(state["trip_details"]["child_ages"])
        prompt = self.prompt_of_last_reply(provider)
        self.assertIn("a child's age is missing", prompt)
        self.assertNotIn("Do what they asked", prompt)

        # "5 anos" - now there is a search, and the card appears with exactly it
        aged, _, state = self.say(provider, "5 anos")
        self.assertTrue(aged.is_accommodation_reply)
        self.assertEqual(
            query_of(self.url_of(aged)),
            [
                ("ss", "Barcelona, Spain"),
                ("checkin", "2026-11-05"),
                ("checkout", "2026-11-15"),
                ("group_adults", "3"),
                ("group_children", "1"),
                ("age", "5"),
            ],
        )
        self.assertEqual(
            aged.trip.caption("Barcelona"),
            "Booking search: Barcelona · 5 Nov 2026 – 15 Nov 2026 (10 nights)"
            " · 3 adults · 1 child (age 5)",
        )
        self.assertEqual(state["trip_details"]["child_ages"], [5])
        prompt = self.prompt_of_last_reply(provider)
        self.assertIn("ages 5 - included in the search", prompt)
        self.assertIn(NO_GUIDE, prompt)
        self.assertNotIn("Needs clarification", prompt)

        # "Quero dois quartos" - the card is drawn again with the rooms, and the
        # earlier button is retired
        rooms, _, _ = self.say(provider, "Quero dois quartos")
        self.assertEqual(dict(query_of(self.url_of(rooms)))["no_rooms"], "2")
        self.assertTrue(rooms.retire_stays)

        # "Na verdade ainda não sei a data" - no search any more: no card, and
        # the buttons already on the page are retired
        cleared, _, state = self.say(provider, "Na verdade ainda não sei a data")
        self.assertEqual(cleared.recommendations, [])
        self.assertTrue(cleared.retire_stays)
        self.assertIsNone(state["trip_details"]["start_date"])
        self.assertEqual(state["trip_details"]["adults"], 3)  # the rest is kept
        self.assertIn("the trip's start date is missing", self.prompt_of_last_reply(provider))
        self.assertEqual(self.selected(), barcelona_record())

    def test_the_cards_the_page_receives_carry_the_same_link_and_caption(self):
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                stays(adults=3, children=1, child_ages=[5]),
                turn(spain(), trip_details={"start": {"day": 5}, "stay_length": 3}),
            ]
        )
        tab = ViewSession(
            self.user, ai_provider=provider, climate_provider=self.climate, save=False
        )
        tab.post("quero ir pra Barcelona")

        tab.post("hospedagem pra 3 adultos e uma criança de 5 anos")
        end = tab.post("quero ir dia 5, 3 dias")

        (card,) = end.cards
        self.assertEqual(
            card["accommodation_caption"],
            "Booking search: Barcelona · 5 Nov 2026 – 8 Nov 2026 (3 nights), month assumed"
            " · 3 adults · 1 child (age 5)",
        )
        self.assertEqual(
            dict(query_of(card["accommodation_search_url"])),
            {
                "ss": "Barcelona, Spain",
                "checkin": "2026-11-05",
                "checkout": "2026-11-08",
                "group_adults": "3",
                "group_children": "1",
                "age": "5",
            },
        )


class CorrectionsAndClearsTests(_TripCase):
    def test_corrections_replace_the_value_and_clear_removes_it(self):
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                stays(adults=2, start={"day": 5}, stay_length=3, stay_unit="days"),
                turn(spain(), trip_details={"start": {"day": 6}}),
                turn(spain(), trip_details={"stay_length": 4, "stay_unit": "nights"}),
                turn(spain(), trip_details={"adults": 3}),
                turn(spain(), trip_details={"cleared_fields": ["start"]}),
                turn(spain(), trip_details={"cleared_fields": ["stay", "adults"]}),
            ]
        )
        self.say(provider, "quero ir pra Barcelona")
        first, _, _ = self.say(provider, "hospedagem dia 5, 3 dias, somos 2")
        self.assertEqual(dict(query_of(self.url_of(first)))["checkout"], "2026-11-08")

        start, _, _ = self.say(provider, "na verdade dia 6")
        self.assertEqual(
            dict(query_of(self.url_of(start))),
            {
                "ss": "Barcelona, Spain",
                "checkin": "2026-11-06",
                "checkout": "2026-11-09",
                "group_adults": "2",
            },
        )

        length, _, _ = self.say(provider, "melhor 4 noites")
        self.assertEqual(dict(query_of(self.url_of(length)))["checkout"], "2026-11-10")
        self.assertEqual(self.stored()["stay_unit"], "nights")

        adults, _, _ = self.say(provider, "na verdade somos 3")
        self.assertEqual(dict(query_of(self.url_of(adults)))["group_adults"], "3")

        no_start, _, _ = self.say(provider, "ainda não sei a data")
        self.assertEqual(no_start.recommendations, [])  # no dates: no search to link to
        self.assertTrue(no_start.retire_stays)  # and the one on the page is out of date
        self.assertIsNone(self.stored()["start_date"])
        self.assertEqual(self.stored()["adults"], 3)

        empty, _, _ = self.say(provider, "esquece a duração e o número de pessoas")
        self.assertEqual(empty.recommendations, [])
        self.assertFalse(empty.retire_stays)  # there was no search before this either
        self.assertIsNone(self.stored())

    def test_a_date_that_has_already_passed_is_asked_about_and_nothing_changes(self):
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                turn(
                    spain(),
                    trip_details={"start": {"day": 5, "relative_month": "this"}, "stay_length": 3},
                ),
            ]
        )
        self.say(provider, "quero ir pra Barcelona")

        result, _, _ = self.say(provider, "quero ir dia 5 deste mês, ficar 3 noites")

        self.assertIsNone(self.stored()["start_date"])
        self.assertEqual(self.stored()["stay_length"], 3)
        prompt = self.prompt_of_last_reply(provider)
        self.assertIn("Monday 5 October 2026, which has already passed", prompt)
        self.assertIn("Ask which date they mean.", prompt)
        self.assertNotIn("Check-in:", prompt)

    def test_a_number_in_a_date_message_never_becomes_a_party_of_one(self):
        # "ficar 3 noites" and "dia 5" are a length and a day. Nobody said who is
        # going, so nobody is: the date that had already passed is the question.
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                stays(
                    start={"day": 5, "relative_month": "this"}, stay_length=3, stay_unit="nights"
                ),
            ]
        )
        self.say(provider, "quero ir pra Barcelona")

        result, _, state = self.say(provider, "quero ir dia 5 deste mês, ficar 3 noites")

        self.assertEqual(result.recommendations, [])
        self.assertIn("already passed", self.prompt_of_last_reply(provider))
        self.assertIsNone(state["trip_details"]["adults"])
        self.assertIsNone(state["trip_details"]["children"])


class LegacyMonthTests(_TripCase):
    def test_the_intent_month_never_drives_the_booking_dates(self):
        # The combined extractor read "dia 05" as month 5. With no trip-details
        # output behind it, there are no dates, so there is no search either.
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                turn(
                    spain(
                        is_accommodation_request=True, accommodation_place_name="Barcelona", month=5
                    ),
                    trip_details={"adults": 2},
                ),
            ]
        )
        self.say(provider, "quero ir pra Barcelona")

        result, intent_sink, _ = self.say(provider, "hospedagem dia 05, somos 2")

        self.assertEqual(intent_sink["month"], 5)
        self.assertFalse(result.trip.has_dates)
        self.assertEqual(result.trip.missing_for_search, ("check_in", "stay_length"))
        self.assertEqual(result.recommendations, [])


class LongStayTests(_TripCase):
    def test_a_stay_over_thirty_nights_reaches_the_link_as_the_traveler_said_it(self):
        # Nothing in Wanderes decides what Booking will take, so a long stay is
        # passed on rather than silently dropped.
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                stays(adults=2, start={"day": 5, "month": 11}, stay_length=45, stay_unit="days"),
            ]
        )
        self.say(provider, "quero ir pra Barcelona")

        result, _, _ = self.say(provider, "hospedagem pra 2, 5 de novembro, 45 dias")

        link = dict(query_of(self.url_of(result)))
        self.assertEqual((link["checkin"], link["checkout"]), ("2026-11-05", "2026-12-20"))
        self.assertIn("(45 nights)", result.trip.caption("Barcelona"))
        self.assertNotIn("longer than", self.prompt_of_last_reply(provider))


LINK_WITH_ROOMS = [
    ("ss", "Barcelona, Spain"),
    ("checkin", "2026-11-05"),
    ("checkout", "2026-11-08"),
    ("group_adults", "3"),
    ("no_rooms", "2"),
    ("group_children", "1"),
    ("age", "5"),
]
NO_GUIDE = "Do NOT write a guide"


class _ActionCase(_TripCase):
    """A conversation already at Barcelona, 5-8 Nov, 3 adults, 1 child aged 5."""

    def conversation(self, *later):
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                stays(adults=3, children=1, child_ages=[5]),
                plain(start={"day": 5}, stay_length=3, stay_unit="days"),
                *later,
            ]
        )
        self.say(provider, "quero ir pra Barcelona")
        self.say(provider, "hospedagem pra 3 adultos e uma criança de 5 anos")
        self.say(provider, "quero ir dia 05 e ficar 3 dias")
        return provider


class RoomsProductionSequenceTests(_TripCase):
    def test_the_whole_production_sequence_ends_with_two_rooms_in_the_search(self):
        provider = ScriptedProvider(
            [
                turn(
                    spain(selected_destination_name="Barcelona"),
                    trip_details={"stay_length": 10, "stay_unit": "days"},
                ),
                stays(),
                stays(start={"day": 5}),
                stays(adults=3, children=1),
                stays(child_ages=[5]),
                plain(start={"day": 5}, stay_length=3, stay_unit="days"),
                stays(rooms=2),
                stays(rooms=2),
            ]
        )
        self.say(provider, "Quero ir pra Barcelona 10 dias")

        asked, _, _ = self.say(provider, "quero hospedagens")
        self.assertEqual(asked.recommendations, [])  # when? - nothing else
        self.assertIn("start date is missing", self.prompt_of_last_reply(provider))

        who, _, _ = self.say(provider, "dia 5")
        self.assertEqual(who.recommendations, [])
        self.assertIn("how many adults", self.prompt_of_last_reply(provider))

        child, _, _ = self.say(provider, "3 adultos e uma criança")
        # An answer to the occupancy question is not a request for a guide:
        # the one thing still missing is the child's age, and that is the reply.
        self.assertEqual(child.recommendations, [])
        self.assertIn("ONE concise question", self.prompt_of_last_reply(provider))
        self.assertIn("a child's age is missing", self.prompt_of_last_reply(provider))
        self.assertNotIn("Do what they asked", self.prompt_of_last_reply(provider))

        aged, _, _ = self.say(provider, "5 anos")
        prompt = self.prompt_of_last_reply(provider)
        self.assertIn("ages 5 - included in the search", prompt)
        self.assertNotIn("ONE concise question", prompt)
        self.assertIn(NO_GUIDE, prompt)
        self.assertEqual(dict(query_of(self.url_of(aged)))["checkout"], "2026-11-15")

        self.say(provider, "quero ir dia 05 e ficar 3 dias")

        rooms, _, state = self.say(provider, "quero dois quartos por favor")
        self.assertEqual(query_of(self.url_of(rooms)), LINK_WITH_ROOMS)
        prompt = self.prompt_of_last_reply(provider)
        self.assertIn("Rooms: 2 - included in the search.", prompt)
        self.assertIn(
            "carries exactly: dates 2026-11-05 to 2026-11-08, 3 adults, 1 children, 2 rooms", prompt
        )
        self.assertIn(NO_GUIDE, prompt)
        self.assertNotIn("asking to book, reserve", prompt)  # no reservation disclaimer
        self.assertNotIn("Points of interest", prompt)  # nothing to describe Barcelona with
        self.assertEqual(
            rooms.trip.caption("Barcelona"),
            "Booking search: Barcelona · 5 Nov 2026 – 8 Nov 2026 (3 nights), month assumed"
            " · 3 adults · 1 child (age 5) · 2 rooms",
        )
        self.assertEqual(
            {k: v for k, v in state["trip_details"].items() if k != "rooms"},
            {
                "start_date": "2026-11-05",
                "start_assumed_month": True,
                "stay_length": 3,
                "stay_unit": "days",
                "adults": 3,
                "children": 1,
                "child_ages": [5],
            },
        )
        self.assertEqual(state["trip_details"]["rooms"], 2)

        again, _, state_again = self.say(provider, "quero uma pesquisa para dois quartos")
        self.assertEqual(query_of(self.url_of(again)), LINK_WITH_ROOMS)  # same action
        self.assertEqual(state_again["trip_details"], state["trip_details"])
        self.assertIn(NO_GUIDE, self.prompt_of_last_reply(provider))


class RoomsMutationRoutingTests(_ActionCase):
    def test_a_rooms_change_is_a_short_action_however_the_intent_labelled_it(self):
        # The intent call has filed "quero dois quartos por favor" three ways.
        for label, turn_for_rooms in (
            ("a stays request", stays(rooms=2)),
            ("ordinary conversation", plain(rooms=2)),
            ("a request to book", booking(rooms=2)),
        ):
            with self.subTest(label=label):
                memory.clear_history(self.key)  # a fresh conversation for each labelling
                provider = self.conversation(turn_for_rooms)

                result, _, _ = self.say(provider, "quero dois quartos por favor")

                self.assertEqual(query_of(self.url_of(result)), LINK_WITH_ROOMS)
                prompt = self.prompt_of_last_reply(provider)
                self.assertNotIn("asking to book, reserve", prompt)  # not the disclaimer prompt
                self.assertNotIn("Points of interest", prompt)
                self.assertIn("Rooms: 2 - included in the search.", prompt)

    def test_a_correction_changes_only_the_rooms(self):
        provider = self.conversation(stays(rooms=2), plain(rooms=1))
        self.say(provider, "quero dois quartos por favor")

        result, _, state = self.say(provider, "na verdade 1 quarto")

        link = dict(query_of(self.url_of(result)))
        self.assertEqual(link["no_rooms"], "1")
        self.assertEqual(
            (link["checkin"], link["checkout"], link["group_adults"]),
            ("2026-11-05", "2026-11-08", "3"),
        )
        self.assertEqual(state["trip_details"]["child_ages"], [5])

    def test_clearing_the_rooms_clears_only_the_rooms(self):
        provider = self.conversation(stays(rooms=2), plain(cleared_fields=["rooms"]))
        self.say(provider, "quero dois quartos por favor")

        result, _, state = self.say(provider, "esquece os quartos")

        self.assertNotIn("no_rooms", dict(query_of(self.url_of(result))))
        self.assertIsNone(state["trip_details"]["rooms"])
        self.assertEqual(state["trip_details"]["adults"], 3)

    def test_two_rooms_never_become_two_adults(self):
        # The model once read "dois quartos" as a party of two.
        provider = self.conversation(stays(adults=2, children=2, rooms=2))

        result, _, state = self.say(provider, "quero uma pesquisa para dois quartos")

        self.assertEqual(
            (state["trip_details"]["adults"], state["trip_details"]["children"]), (3, 1)
        )
        self.assertEqual(state["trip_details"]["child_ages"], [5])
        self.assertEqual(state["trip_details"]["rooms"], 2)

    def test_a_stray_age_of_zero_does_not_replace_the_known_age_but_a_correction_does(self):
        provider = self.conversation(
            stays(rooms=2, child_ages=[0]),  # a spurious 0 beside a rooms request
            plain(child_ages=[0]),  # the traveler really correcting it
        )

        _, _, state = self.say(provider, "quero dois quartos por favor")
        self.assertEqual(state["trip_details"]["child_ages"], [5])

        _, _, state = self.say(provider, "na verdade ela tem 0 anos")
        self.assertEqual(state["trip_details"]["child_ages"], [0])

    def test_a_stray_age_of_zero_beside_the_party_keeps_the_known_age(self):
        provider = self.conversation(plain(adults=3, children=1, child_ages=[0]))

        _, _, state = self.say(provider, "somos 3 adultos e uma criança")

        self.assertEqual(state["trip_details"]["child_ages"], [5])

    def test_a_rooms_message_makes_exactly_one_extra_call_and_a_cue_less_one_none(self):
        provider = self.conversation(plain(rooms=1))
        calls = len(provider.structured_calls)

        self.say(provider, "quero um quarto")

        self.assertEqual(provider.structured_calls[calls:].count("trip_details_signal"), 1)


class BookingWordingTests(_ActionCase):
    def test_reserve_two_rooms_applies_the_rooms_and_says_the_limit_in_one_clause(self):
        provider = self.conversation(booking(rooms=2))

        result, _, state = self.say(provider, "reserve dois quartos para mim")

        self.assertEqual(query_of(self.url_of(result)), LINK_WITH_ROOMS)
        self.assertEqual(state["trip_details"]["rooms"], 2)
        prompt = self.prompt_of_last_reply(provider)
        self.assertIn("They used booking wording", prompt)
        self.assertIn("the reservation is finished on Booking.com", prompt)
        self.assertIn("never refuse the request", prompt)
        self.assertNotIn("asking to book, reserve", prompt)

    def test_a_booking_request_for_the_chosen_place_gets_the_search_not_a_planning_pivot(self):
        provider = self.conversation(booking())

        result, _, _ = self.say(provider, "reserve um hotel pra mim")

        self.assertTrue(result.recommendations)  # the existing stays search
        prompt = self.prompt_of_last_reply(provider)
        self.assertIn("They used booking wording", prompt)
        self.assertNotIn("help them think through destinations", prompt)

    def test_a_booking_request_with_nowhere_to_search_keeps_the_limit_and_points_at_the_search(
        self,
    ):
        provider = ScriptedProvider([booking()])

        result, _, _ = self.say(provider, "reserve um hotel pra mim")

        self.assertEqual(result.recommendations, [])
        prompt = self.prompt_of_last_reply(provider)
        self.assertIn("asking to book, reserve", prompt)
        self.assertIn("You cannot actually make bookings", prompt)
        self.assertIn("set up a stay search once they tell you where", prompt)
        self.assertIn("Don't pivot to destination ideas or general travel planning", prompt)

    def test_a_booking_request_with_nothing_to_search_with_asks_for_it_and_states_the_limit(self):
        provider = ScriptedProvider([turn(spain(selected_destination_name="Barcelona")), booking()])
        self.say(provider, "quero ir pra Barcelona")

        result, _, _ = self.say(provider, "reserve um hotel pra mim")

        self.assertEqual(result.recommendations, [])
        prompt = self.prompt_of_last_reply(provider)
        self.assertIn("the trip's start date is missing", prompt)
        self.assertIn("They used booking wording", prompt)


class GenericAndInformationalStaysTests(_ActionCase):
    def test_a_generic_stays_request_is_a_search_action_not_a_guide(self):
        for message in ("quero hospedagens", "me ajuda com hospedagem"):
            with self.subTest(message=message):
                provider = self.conversation(stays())

                result, _, _ = self.say(provider, message)

                self.assertTrue(result.recommendations)  # the search action
                prompt = self.prompt_of_last_reply(provider)
                self.assertIn(NO_GUIDE, prompt)
                self.assertIn("say in a sentence or two that the search is ready", prompt)
                self.assertNotIn("Points of interest", prompt)
                self.assertNotIn("Description:", prompt)

    def test_a_question_about_areas_is_still_allowed_its_answer(self):
        provider = self.conversation(stays())

        result, _, _ = self.say(provider, "qual bairro é melhor para ficar?")

        prompt = self.prompt_of_last_reply(provider)
        self.assertIn(
            "unless their message actually asks for that - and then answer just that question",
            prompt,
        )
        self.assertTrue(result.recommendations)

    def test_an_unsupported_filter_gets_the_limit_and_the_nearest_action(self):
        provider = self.conversation(stays())

        result, _, _ = self.say(provider, "quero hotel barato")

        prompt = self.prompt_of_last_reply(provider)
        self.assertIn(
            "Only when their message itself asks for something the search can't do", prompt
        )
        self.assertIn("star rating, property type, amenity (pool, breakfast, pet-friendly)", prompt)
        self.assertIn("cheap, barato, luxury", prompt)
        self.assertIn("Never describe the search as being for that", prompt)
        # ... and the facts carry the same limit, triggered by the words themselves.
        self.assertIn("asked for a price level, star rating or amenity", prompt)
        self.assertIn("Never describe the search as being for it", prompt)
        self.assertIn("Otherwise never mention filters, prices or availability at all", prompt)
        self.assertIn("Wanderes has no verified live prices and can't filter", prompt)
        self.assertIn("they can apply it once the Booking search is open", prompt)
        self.assertIn("don't recommend specific hotels or quote prices", prompt)
        self.assertEqual(
            dict(query_of(self.url_of(result)))["group_adults"], "3"
        )  # the search itself carries no invented filter
        self.assertNotIn("order", dict(query_of(self.url_of(result))))

    def test_the_limit_is_triggered_by_the_words_and_only_by_them(self):
        for message, expect_line in (
            ("quero hotel barato", True),
            ("quero um hotel de luxo com piscina", True),
            ("hotel de 4 estrelas", True),
            ("quero hospedagens", False),
            ("quanto custa?", False),
            ("qual bairro é melhor para ficar?", False),
        ):
            with self.subTest(message=message):
                memory.clear_history(self.key)
                provider = self.conversation(stays())

                self.say(provider, message)

                line = "asked for a price level, star rating or amenity"
                self.assertEqual(line in self.prompt_of_last_reply(provider), expect_line)

    def test_a_filter_request_costs_no_extra_model_call(self):
        provider = self.conversation(stays())
        calls = len(provider.structured_calls)

        self.say(provider, "quero hotel barato")

        self.assertNotIn("trip_details_signal", provider.structured_calls[calls:])

    def test_nothing_in_the_stays_prompt_invites_a_preference_or_an_intent(self):
        provider = self.conversation(stays())
        self.say(provider, "quero hospedagens")

        prompt = self.prompt_of_last_reply(provider)

        self.assertIn(
            "Never invent a preference, intent, question or need they didn't express", prompt
        )
        self.assertIn(
            "Never write a URL or a link yourself, and don't announce one", prompt
        )

class UnsupportedFilterScopeTests(_ActionCase):
    """A price level, star rating or amenity is something the Booking search can't
    apply, so it is said to a traveler working on that search - and only then."""

    LINE = "asked for a price level, star rating or amenity"

    def test_an_informational_question_is_never_told_the_search_cannot_filter(self):
        for message in (
            "onde comer barato em Barcelona?",
            "restaurantes baratos perto da Sagrada Família?",
            "are there cheap tapas bars?",
            "é um destino caro?",
        ):
            with self.subTest(message=message):
                memory.clear_history(self.key)
                provider = self.conversation(plain())

                self.say(provider, message)

                self.assertNotIn(self.LINE, self.prompt_of_last_reply(provider))

    def test_choosing_a_destination_in_words_that_mention_a_budget_is_not_a_stays_request(self):
        provider = ScriptedProvider([turn(spain(selected_destination_name="Barcelona"))])

        self.say(provider, "quero ir pra Barcelona, algo barato")

        self.assertNotIn(self.LINE, self.prompt_of_last_reply(provider))

    def test_a_stays_search_for_one_still_gets_it(self):
        provider = self.conversation(stays())

        self.say(provider, "quero um hotel barato")

        self.assertIn(self.LINE, self.prompt_of_last_reply(provider))

    def test_the_limitation_does_not_claim_the_supported_details_are_missing(self):
        provider = self.conversation(stays())

        self.say(provider, "quero um hotel de luxo com piscina")

        prompt = self.prompt_of_last_reply(provider)
        self.assertNotIn("no verified live prices or filters", prompt)
        self.assertIn("can't filter the Booking search by price level, star rating", prompt)
        self.assertIn("The Booking search link carries exactly: dates", prompt)  # dates are in


class PendingDetailTests(_TripCase):
    def pending_age(self, *later):
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                stays(adults=3, children=1, **WHEN),
                *later,
            ]
        )
        self.say(provider, "quero ir pra Barcelona")
        self.say(provider, "hospedagem pra 3 adultos e uma criança dia 5, 3 dias")
        return provider

    def test_a_request_that_names_the_children_while_the_age_is_missing_asks_for_the_age_only(self):
        provider = self.pending_age(stays())

        result, _, _ = self.say(provider, "quero hospedagem para crianças")

        prompt = self.prompt_of_last_reply(provider)
        self.assertIn("ONE concise question", prompt)
        self.assertIn("a child's age is missing", prompt)
        self.assertNotIn("Do what they asked", prompt)  # no guide, no suggestions
        self.assertEqual(result.recommendations, [])  # and no search while the age is missing

    def test_a_generic_request_while_the_age_is_missing_asks_for_it(self):
        provider = self.pending_age(stays())

        result, _, _ = self.say(provider, "quero hospedagens")

        prompt = self.prompt_of_last_reply(provider)
        self.assertIn("a child's age is missing", prompt)
        self.assertIn("ask ONE concise question", prompt)
        self.assertIn("Never say a search or a link is ready", prompt)
        self.assertEqual(result.recommendations, [])

    def test_a_question_about_areas_while_the_age_is_missing_is_not_blocked(self):
        provider = self.pending_age(stays())

        result, _, _ = self.say(provider, "qual bairro é melhor para ficar?")

        prompt = self.prompt_of_last_reply(provider)
        self.assertIn("answer that first, briefly and helpfully", prompt)  # answered, then asked
        self.assertIn("a child's age is missing", prompt)
        self.assertEqual(result.recommendations, [])

    def test_the_conversation_goes_on_asking_until_the_action_is_representable(self):
        provider = self.pending_age(stays(), stays(child_ages=[5]))

        first, _, _ = self.say(provider, "quero hospedagem para crianças")
        result, _, _ = self.say(provider, "5 anos")

        self.assertEqual(first.recommendations, [])
        self.assertEqual(
            dict(query_of(self.url_of(result))),
            {
                "ss": "Barcelona, Spain",
                "checkin": "2026-11-05",
                "checkout": "2026-11-08",
                "group_adults": "3",
                "group_children": "1",
                "age": "5",
            },
        )
        self.assertIn(NO_GUIDE, self.prompt_of_last_reply(provider))
        self.assertNotIn("ONE concise question", self.prompt_of_last_reply(provider))


class RoomsMoreThanAdultsTests(_TripCase):
    def conversation(self, *later):
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                stays(adults=1, rooms=3, **WHEN),
                *later,
            ]
        )
        self.say(provider, "quero ir pra Barcelona")
        return provider

    def test_three_rooms_for_one_adult_is_asked_about_and_never_claimed(self):
        provider = self.conversation()

        result, _, state = self.say(provider, "1 adulto, 3 quartos")

        prompt = self.prompt_of_last_reply(provider)
        self.assertIn("ONE concise question", prompt)
        self.assertIn("3 rooms can't go in the search with 1 adult(s)", prompt)
        self.assertIn(
            "whether to change the number of adults or use fewer rooms (at most 1)", prompt
        )
        self.assertIn("the rooms are NOT in the Booking search", prompt)
        self.assertEqual(result.recommendations, [])  # nothing to link to until it is settled
        self.assertEqual(result.trip.missing_for_search, ("rooms",))
        self.assertIsNone(result.trip.search_kwargs())  # never no_rooms=3, never a smaller search
        self.assertEqual(state["trip_details"]["rooms"], 3)  # what they asked for stays on record

    def test_either_answer_makes_the_rooms_representable(self):
        for answer, components, expected in (
            ("1 quarto mesmo", {"rooms": 1}, "1"),
            ("então somos 3 adultos", {"adults": 3}, "3"),
        ):
            with self.subTest(answer=answer):
                provider = self.conversation(plain(**components))
                self.say(provider, "1 adulto, 3 quartos")

                result, _, _ = self.say(provider, answer)

                self.assertEqual(dict(query_of(self.url_of(result)))["no_rooms"], expected)

    def test_rooms_that_stop_fitting_take_the_search_away_and_the_old_button_with_it(self):
        provider = self.conversation(plain(rooms=1), plain(rooms=3))
        self.say(provider, "1 adulto, 3 quartos")
        fits, _, _ = self.say(provider, "1 quarto mesmo")
        self.assertEqual(dict(query_of(self.url_of(fits)))["no_rooms"], "1")

        result, _, state = self.say(provider, "quero 3 quartos")

        self.assertEqual(state["trip_details"]["rooms"], 3)
        self.assertEqual(result.recommendations, [])
        self.assertTrue(result.retire_stays)  # the search with 1 room is out of date
        self.assertIn("3 rooms can't go in the search", self.prompt_of_last_reply(provider))

    def test_a_search_request_while_the_rooms_still_do_not_fit_asks_again_and_offers_nothing(self):
        provider = self.conversation(stays())
        self.say(provider, "1 adulto, 3 quartos")

        result, _, _ = self.say(provider, "quero hospedagens")

        self.assertEqual(result.recommendations, [])
        self.assertIn("3 rooms can't go in the search", self.prompt_of_last_reply(provider))

    def test_taking_the_rooms_back_makes_the_search_ready_though_the_link_would_not_differ(self):
        provider = self.conversation(plain(cleared_fields=["rooms"]))
        self.say(provider, "1 adulto, 3 quartos")

        result, _, state = self.say(provider, "esquece os quartos")

        # What the link would carry is the same as before (the 3 rooms were never in it),
        # but there was no search then and there is one now.
        self.assertEqual(
            dict(query_of(self.url_of(result))),
            {
                "ss": "Barcelona, Spain",
                "checkin": "2026-11-05",
                "checkout": "2026-11-08",
                "group_adults": "1",
            },
        )
        self.assertIsNone(state["trip_details"]["rooms"])
        self.assertTrue(result.retire_stays)


class InventedLinkTests(_ActionCase):
    """The model can't know the real search URL and writes one when it can; the
    card beside the reply carries the actual link, so none of that gets out."""

    INVENTED = (
        "Pronto! [Pesquisar hospedagens](https://www.booking.com/searchresults.pt-br.html"
        "?ss=Barcelona&no_rooms=3) Boa viagem!"
    )

    def spoken(self, provider, message):
        from ai.orchestration import stream_travel_recommendation

        result = stream_travel_recommendation(
            message, user=self.user, ai_provider=provider, climate_provider=self.climate
        )
        return result, "".join(result.reply_chunks)

    def test_a_stays_action_reply_never_carries_a_link_the_model_wrote(self):
        provider = self.conversation(plain(rooms=2))
        provider.reply_text = self.INVENTED

        result, spoken = self.spoken(provider, "quero dois quartos por favor")

        self.assertEqual(spoken, "Pronto! Pesquisar hospedagens Boa viagem!")
        self.assertNotIn("booking.com", memory.get_history(self.key)[-1]["content"])
        self.assertIn("no_rooms=2", self.url_of(result))  # the card's link is the real one

    def test_a_search_request_reply_is_held_to_the_same(self):
        provider = self.conversation(stays())
        provider.reply_text = self.INVENTED

        _, spoken = self.spoken(provider, "quero hospedagens")

        self.assertNotIn("http", spoken)

    def test_the_question_about_who_is_going_is_held_to_the_same(self):
        provider = ScriptedProvider([turn(spain(selected_destination_name="Barcelona")), stays()])
        provider.reply_text = self.INVENTED
        self.say(provider, "quero ir pra Barcelona")

        result, spoken = self.spoken(provider, "quero hospedagens")

        self.assertEqual(result.recommendations, [])  # nothing to search yet - just the question
        self.assertNotIn("http", spoken)
        self.assertNotIn("booking.com", memory.get_history(self.key)[-1]["content"])

    def test_what_the_traveler_is_shown_is_what_is_remembered(self):
        provider = self.conversation(plain(rooms=2))
        provider.reply_text = self.INVENTED

        _, spoken = self.spoken(provider, "quero dois quartos por favor")

        self.assertEqual(memory.get_history(self.key)[-1]["content"], spoken)

    def test_other_replies_are_left_alone(self):
        provider = self.conversation(plain())
        provider.reply_text = "Veja https://example.com/guia"

        _, spoken = self.spoken(provider, "obrigado")

        self.assertEqual(spoken, "Veja https://example.com/guia")


class RoomsStateTests(_OrchestrationCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch("ai.orchestration._today", return_value=TODAY)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def _t(trip=None):
        return {
            "intent": intent(),
            "climate_budget": {},
            "state_clear": {},
            "trip_details": trip or {},
        }

    def test_the_owner_writes_the_rooms_and_a_foreign_conversation_does_not(self):
        self._own(5, trip_details={"adults": 3})

        _, owned = self._override_turn(
            ScriptedProvider([self._t({"rooms": 2})]), 5, message="quero dois quartos"
        )
        self.assertEqual(owned["trip_details"]["rooms"], 2)

        _, foreign = self._override_turn(
            ScriptedProvider([self._t({"rooms": 9})]), 6, message="quero nove quartos"
        )
        self.assertEqual(foreign, {})
        self.assertEqual(memory.get_climate_budget(self.key)["trip_details"]["rooms"], 2)
        self.assertEqual(memory.get_state_owner(self.key), 5)


class StaysActionResurfacingTests(_TripCase):
    """On a turn that only carries the destination, the stays action comes
    back when - and only when - what the link carries has changed."""

    def test_details_that_leave_the_search_unready_are_answered_with_the_next_question(self):
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                turn(spain(), trip_details={"stay_length": 3, "stay_unit": "days"}),
                turn(spain(), trip_details={"adults": 3}),
                turn(spain(), trip_details={"children": 1}),
                turn(spain(), trip_details={"start": {"day": 5}}),
                turn(spain(), trip_details={"child_ages": [5]}),
            ]
        )
        self.say(provider, "quero ir pra Barcelona")

        messages = ("me ajuda a montar um roteiro de 3 dias?", "somos 3 adultos", "e uma criança")
        for message in messages:
            result, _, _ = self.say(provider, message)

            # Still no start date: that stays the one question, and nothing is
            # offered or retired, because there was no search and there is none.
            self.assertEqual(result.recommendations, [])
            self.assertFalse(result.retire_stays)
            self.assertIn("the trip's start date is missing", self.prompt_of_last_reply(provider))

        date_given, _, _ = self.say(provider, "dia 5")
        self.assertEqual(date_given.recommendations, [])
        self.assertIn("a child's age is missing", self.prompt_of_last_reply(provider))

        ready, _, _ = self.say(provider, "5 anos")
        self.assertEqual(dict(query_of(self.url_of(ready)))["age"], "5")

    def test_a_turn_that_changes_nothing_brings_nothing_back(self):
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                stays(adults=2),
                turn(spain(), trip_details={"adults": 2}),
            ]
        )
        self.say(provider, "quero ir pra Barcelona")
        self.say(provider, "hospedagem pra 2")

        same, _, _ = self.say(provider, "isso, somos 2 mesmo")

        self.assertEqual(same.recommendations, [])

    def test_the_resurfaced_action_is_not_a_new_selection(self):
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                turn(
                    spain(),
                    trip_details={"start": {"day": 5}, "stay_length": 3, "adults": 2},
                ),
            ]
        )
        self.say(provider, "quero ir pra Barcelona")

        dated, _, _ = self.say(provider, "dia 5, 3 dias, somos 2")

        self.assertTrue(dated.is_accommodation_reply)  # so the view records no selection event
        self.assertTrue(dated.is_destination_detail)


class ComplaintDoesNotWipeTheTripTests(_TripCase):
    def test_a_complaint_about_the_date_takes_back_the_date_not_the_party_or_the_length(self):
        # The model once answered "continua com a data errada" by clearing
        # everything. Only what the message names can be cleared.
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                stays(adults=2, start={"day": 20}, stay_length=3, stay_unit="nights"),
                turn(
                    spain(),
                    trip_details={"cleared_fields": ["start", "stay", "adults", "children"]},
                ),
            ]
        )
        self.say(provider, "quero ir pra Barcelona")
        self.say(provider, "hospedagem pra 2, dia 20, 3 noites")

        self.say(provider, "continua com a data errada")

        self.assertIsNone(self.stored()["start_date"])
        self.assertEqual(self.stored()["adults"], 2)
        self.assertEqual(self.stored()["stay_length"], 3)


class ModelCallImpactTests(_TripCase):
    def test_ordinary_conversation_on_a_chosen_destination_makes_no_extra_call(self):
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                turn(spain()),
                turn(spain()),
                turn(spain()),
                turn(spain(is_activity_question=True, activity_place_name="Barcelona")),
            ]
        )
        self.say(provider, "quero ir pra Barcelona")
        calls_so_far = len(provider.structured_calls)

        for message in ("obrigado", "quanto custa?", "conte-me mais sobre Barcelona"):
            self.say(provider, message)
        self.say(provider, "o que fazer lá?")

        self.assertEqual(self.trip_calls(provider), 0)
        self.assertEqual(
            provider.structured_calls[calls_so_far:],
            _MERGE_PATH_CALLS * 3 + ["travel_message"],
        )

    def test_a_message_with_trip_cues_makes_exactly_one_extra_call(self):
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                turn(spain(), trip_details={"start": {"day": 5}}),
            ]
        )
        self.say(provider, "quero ir pra Barcelona")
        calls_so_far = len(provider.structured_calls)

        self.say(provider, "quero ir dia 5")

        self.assertEqual(self.trip_calls(provider), 1)
        self.assertEqual(
            provider.structured_calls[calls_so_far:],
            [
                "travel_message",
                "trip_details_signal",
                "climate_budget_signal",
                "traveler_state_clear_signal",
            ],
        )

    def test_a_stays_request_waiting_on_occupancy_reads_it_even_without_a_cue(self):
        provider = ScriptedProvider([turn(spain(selected_destination_name="Barcelona")), stays()])
        self.say(provider, "quero ir pra Barcelona")

        self.say(provider, "quero hospedagens")

        self.assertEqual(self.trip_calls(provider), 1)

    def test_a_stays_request_with_adults_already_known_needs_no_call(self):
        provider = ScriptedProvider(
            [turn(spain(selected_destination_name="Barcelona")), stays(adults=2), stays()]
        )
        self.say(provider, "quero ir pra Barcelona")
        self.say(provider, "hospedagem pra 2")

        again, _, _ = self.say(provider, "e hospedagem de novo?")

        self.assertEqual(self.trip_calls(provider), 1)  # only the turn that said "2"
        self.assertEqual(again.trip.adults, 2)
        self.assertFalse(again.trip.has_dates)

    def test_messages_that_are_not_about_this_trip_are_not_read(self):
        provider = ScriptedProvider(
            [
                turn(spain(message_type="feedback", feedback_destination_name="Rome")),
                turn(spain(message_type="future_intent", future_destination_name="Rome")),
                turn(spain(is_video_request=True, video_place_name="Spain")),
            ]
        )

        self.say(provider, "estive em Roma em 2019 e adorei")
        self.say(provider, "um dia em 2030 quero ir pra Roma")
        self.say(provider, "tem vídeo de Roma, 3 minutos?")

        self.assertEqual(self.trip_calls(provider), 0)

    def test_the_call_sees_the_message_and_only_a_digit_masked_last_question(self):
        provider = ScriptedProvider(
            [turn(spain(selected_destination_name="Barcelona")), stays(adults=3, children=1)]
        )
        provider.reply_text = "Quantas pessoas? Já falei de 4 pessoas antes."
        self.say(provider, "quero ir pra Barcelona")
        self.say(provider, "3 adultos e uma criança")

        (messages,) = provider.trip_details_messages
        system, user = messages[0].content, messages[-1].content

        self.assertIn("never take a number or detail from it", system)
        self.assertEqual(len(messages), 2)  # no history rides along
        self.assertIn("3 adultos e uma criança", user)
        self.assertIn("Quantas pessoas?", user)  # the assistant's last message, for context
        self.assertNotIn("4 pessoas", user)
        self.assertIn("# pessoas", user)


class ProfileNeverSeedsTheTripTests(_TripCase):
    def test_a_usual_group_size_in_the_profile_is_not_this_trips_party(self):
        TravelerProfile.objects.create(user=self.user, travelers_count=4, home_country="Brazil")
        provider = ScriptedProvider([turn(spain(selected_destination_name="Barcelona")), stays()])
        self.say(provider, "quero ir pra Barcelona")

        result, _, state = self.say(provider, "quero hospedagens")

        self.assertEqual(result.recommendations, [])  # asked who is going
        self.assertIsNone(state["trip_details"])
        self.assertNotIn("usually travels with", self.prompt_of_last_reply(provider))

    def test_a_stays_reply_does_not_repeat_the_profiles_group_size_either(self):
        TravelerProfile.objects.create(user=self.user, travelers_count=4, home_country="Brazil")
        provider = ScriptedProvider(
            [turn(spain(selected_destination_name="Barcelona")), stays(adults=2, **WHEN)]
        )
        self.say(provider, "quero ir pra Barcelona")

        result, _, _ = self.say(provider, "hospedagem pra 2")

        self.assertEqual(dict(query_of(self.url_of(result)))["group_adults"], "2")
        self.assertNotIn("usually travels with", self.prompt_of_last_reply(provider))


class FactsInOrdinaryRepliesTests(_TripCase):
    def test_a_reply_that_does_not_ask_carries_no_facts_when_nothing_is_known(self):
        provider = ScriptedProvider(
            [turn(spain(selected_destination_name="Barcelona")), turn(spain())]
        )
        self.say(provider, "quero ir pra Barcelona")
        # choosing a place asks for the start date, so it is told what is missing
        self.assertIn("the trip's start date is missing", self.prompt_of_last_reply(provider))

        self.say(provider, "obrigado")

        self.assertNotIn("Trip details Wanderes holds", self.prompt_of_last_reply(provider))

    def test_once_something_is_known_every_reply_on_the_trip_is_told_exactly_that(self):
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                turn(spain(), trip_details={"adults": 2}),
                turn(spain()),
            ]
        )
        self.say(provider, "quero ir pra Barcelona")
        self.say(provider, "somos 2")

        self.say(provider, "quanto custa?")

        prompt = self.prompt_of_last_reply(provider)
        self.assertIn("Adults: 2.", prompt)
        self.assertIn("There is NO Booking search action yet", prompt)
        self.assertNotIn("Needs clarification", prompt)  # an ordinary reply doesn't ask
        self.assertIn("never say one was set, changed or corrected unless they say so", prompt)


class StateAndOwnershipTests(_OrchestrationCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch("ai.orchestration._today", return_value=TODAY)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def _t(trip=None):
        return {
            "intent": intent(),
            "climate_budget": {},
            "state_clear": {},
            "trip_details": trip or {},
        }

    def stored(self):
        return memory.get_climate_budget(self.key)["trip_details"]

    def test_the_record_is_part_of_the_accumulated_state_and_a_new_conversation_drops_it(self):
        self._turn(ScriptedProvider([self._t({"adults": 2})]), "somos 2")

        self.assertEqual(self.stored()["adults"], 2)
        memory.clear_history(self.key)

        self.assertIsNone(self.stored())

    def test_set_unchanged_and_clear_at_the_state_level(self):
        memory.update_climate_budget(self.key, trip_details={"adults": 2})
        self.assertEqual(memory.get_climate_budget(self.key)["trip_details"], {"adults": 2})

        memory.update_climate_budget(self.key, trip_type="beach")  # untouched by other fields
        self.assertEqual(memory.get_climate_budget(self.key)["trip_details"], {"adults": 2})

        memory.update_climate_budget(self.key, trip_details_cleared=True)
        self.assertIsNone(memory.get_climate_budget(self.key)["trip_details"])
        self.assertEqual(
            memory.resolve_state_delta(trip_details={"adults": 1})["trip_details"], {"adults": 1}
        )

    def test_the_owning_conversation_reads_and_writes_the_record_and_keeps_ownership(self):
        self._own(5, trip_details={"adults": 2})
        provider = ScriptedProvider([self._t({"stay_length": 3, "stay_unit": "nights"})])

        _, state = self._override_turn(provider, 5, message="ficar 3 noites")

        self.assertEqual(state["trip_details"]["adults"], 2)  # carried over
        self.assertEqual(state["trip_details"]["stay_length"], 3)
        self.assertEqual(self.stored()["stay_length"], 3)
        self.assertEqual(memory.get_state_owner(self.key), 5)

    def test_a_conversation_that_does_not_own_the_state_leaves_the_record_alone(self):
        self._own(5, trip_details={"adults": 2})
        provider = ScriptedProvider([self._t({"adults": 9})])

        _, state = self._override_turn(provider, 6, message="somos 9")

        self.assertEqual(state, {})  # ran stateless
        self.assertEqual(self.stored(), {"adults": 2})
        self.assertEqual(memory.get_state_owner(self.key), 5)

    def test_a_conversation_that_does_not_own_the_state_cannot_leave_an_offer_in_it(self):
        TravelerProfile.objects.create(user=self.user, travelers_count=2)
        dates = {"start_date": "2026-11-05", "stay_length": 3, "stay_unit": "days"}
        self._own(5, trip_details=dates)
        stays_turn = {
            "intent": intent(is_accommodation_request=True, accommodation_place_name="Rome"),
            "climate_budget": {},
            "state_clear": {},
            "trip_details": {**WHEN},
        }

        self._override_turn(ScriptedProvider([stays_turn]), 6, message="hospedagem dia 5, 3 dias")

        self.assertEqual(self.stored(), dates)  # the other conversation's state, untouched
        self.assertEqual(memory.get_state_owner(self.key), 5)

    def test_the_owning_conversation_records_the_question_it_asked(self):
        TravelerProfile.objects.create(user=self.user, travelers_count=2)
        dates = {"start_date": "2026-11-05", "stay_length": 3, "stay_unit": "days"}
        self._own(5, trip_details=dates)
        stays_turn = {
            "intent": intent(is_accommodation_request=True, accommodation_place_name="Rome"),
            "climate_budget": {},
            "state_clear": {},
            "trip_details": {},
        }

        self._override_turn(ScriptedProvider([stays_turn]), 5, message="quero hospedagens")

        self.assertEqual(self.stored()["adults_offer"], 2)
        self.assertEqual(memory.get_state_owner(self.key), 5)

    def test_a_conversation_that_loses_the_state_mid_turn_leaves_no_offer_in_it(self):
        TravelerProfile.objects.create(user=self.user, travelers_count=2)
        dates = {"start_date": "2026-11-05", "stay_length": 3, "stay_unit": "days"}
        self._own(5, trip_details=dates)
        stays_turn = {
            "intent": intent(is_accommodation_request=True, accommodation_place_name="Rome"),
            "climate_budget": {},
            "state_clear": {},
            "trip_details": {},
        }
        provider = ScriptedProvider([stays_turn])
        provider.before_call = lambda schema: (
            schema == "trip_details_signal" and self._own(6, trip_details=dates)
        )

        self._override_turn(provider, 5, message="quero hospedagens")

        self.assertEqual(self.stored(), dates)  # the new owner's state, with no question in it
        self.assertEqual(memory.get_state_owner(self.key), 6)

    def test_a_stateless_turn_resolves_from_its_own_message_only_and_never_persists(self):
        first = ScriptedProvider([self._t({"start": {"day": 5}})])
        second = ScriptedProvider([self._t({"adults": 3})])

        self._override_turn(first, None, message="dia 5")
        self._override_turn(second, None, message="somos 3")

        self.assertIsNone(self.stored())  # nothing was written, so nothing carried over

    def test_losing_ownership_during_the_model_call_skips_the_write(self):
        self._own(5, trip_details={"adults": 2})
        provider = ScriptedProvider([self._t({"adults": 7})])
        # Another conversation takes the state while this turn's model calls run.
        provider.before_call = lambda name: (
            memory.update_climate_budget(self.key, trip_details={"adults": 4}, owner=6)
            if name == "trip_details_signal"
            else None
        )

        self._override_turn(provider, 5, message="somos 7")

        self.assertEqual(self.stored(), {"adults": 4})  # the other writer's, untouched
        self.assertEqual(memory.get_state_owner(self.key), 6)


class ProfileSuggestionTests(_TripCase):
    """The profile's party size is a question to ask, never an answer to use."""

    def setUp(self):
        super().setUp()
        TravelerProfile.objects.create(user=self.user, travelers_count=2)

    def provider(self, *later):
        return ScriptedProvider(
            [turn(spain(selected_destination_name="Barcelona"), trip_details=WHEN), *later]
        )

    def choose(self, provider):
        return self.say(provider, "quero ir pra Barcelona dia 5, 3 dias")

    def test_the_profiles_party_is_asked_about_and_nothing_is_assumed(self):
        provider = self.provider()

        chosen, _, _ = self.choose(provider)

        prompt = self.prompt_of_last_reply(provider)
        self.assertIn("profile says they usually travel with 2 people", prompt)
        self.assertIn("whether those 2 people are all adults", prompt)
        self.assertFalse(self.has_search(chosen))
        self.assertIsNone(self.stored()["adults"])
        self.assertEqual(self.stored()["adults_offer"], 2)

    def test_a_clear_yes_confirms_it_into_the_trip_and_the_search_appears(self):
        provider = self.provider(plain(confirms_party_offer=True))
        self.choose(provider)

        result, _, state = self.say(provider, "sim")

        self.assertEqual(state["trip_details"]["adults"], 2)
        self.assertNotIn("adults_offer", state["trip_details"])
        self.assertEqual(dict(query_of(self.url_of(result)))["group_adults"], "2")
        self.assertEqual(self.trip_calls(provider), 2)  # the "sim" was read: a question was open

    def test_who_is_going_in_the_traveler_own_words_wins_over_the_suggestion(self):
        provider = self.provider(plain(adults=3, confirms_party_offer=True))
        self.choose(provider)

        result, _, state = self.say(provider, "na verdade somos 3")

        self.assertEqual(state["trip_details"]["adults"], 3)
        self.assertEqual(dict(query_of(self.url_of(result)))["group_adults"], "3")

    def test_anything_but_a_yes_lets_the_suggestion_lapse_for_good(self):
        provider = self.provider(plain(), plain(confirms_party_offer=True))
        self.choose(provider)

        no, _, _ = self.say(provider, "não, por quê?")
        self.assertNotIn("adults_offer", self.stored())
        self.assertFalse(self.has_search(no))

        late, _, state = self.say(provider, "sim")  # a stray yes a turn later
        self.assertIsNone(state["trip_details"]["adults"])
        self.assertEqual(self.trip_calls(provider), 2)  # no question open, nothing to read

    def test_a_reply_that_does_not_ask_leaves_no_suggestion_behind(self):
        provider = self.provider(plain(), plain())
        self.choose(provider)
        self.say(provider, "qual a moeda de lá?")  # the open question lapses ...

        reply, _, _ = self.say(provider, "e o clima?")  # ... and an answer doesn't re-ask

        self.assertNotIn("adults_offer", self.stored())
        self.assertNotIn("Needs clarification", self.prompt_of_last_reply(provider))

    def test_it_is_only_offered_when_who_is_going_is_the_next_thing_to_ask(self):
        provider = ScriptedProvider([turn(spain(selected_destination_name="Barcelona"))])

        self.say(provider, "quero ir pra Barcelona")  # the start date comes first

        prompt = self.prompt_of_last_reply(provider)
        self.assertIn("the trip's start date is missing", prompt)
        self.assertNotIn("whether those", prompt)
        self.assertIsNone(self.stored())

    def test_a_profile_without_a_usable_party_gets_the_plain_question(self):
        for count in (None, 0, 99):
            with self.subTest(travelers_count=count):
                memory.clear_history(self.key)
                TravelerProfile.objects.filter(user=self.user).update(travelers_count=count)
                provider = self.provider()

                self.choose(provider)

                prompt = self.prompt_of_last_reply(provider)
                self.assertIn("how many adults are going and whether any children", prompt)
                self.assertNotIn("whether those", prompt)
                self.assertNotIn("adults_offer", self.stored())

    def test_nobody_signed_out_has_a_profile_to_suggest_from(self):
        provider = self.provider()

        result = stream_travel_recommendation(
            "quero ir pra Barcelona dia 5, 3 dias",
            user=None,
            session_key="anonymous-visitor",
            ai_provider=provider,
            climate_provider=self.climate,
        )
        "".join(result.reply_chunks)

        key = memory.conversation_key(user=None, session_key="anonymous-visitor")
        self.assertNotIn("adults_offer", memory.get_climate_budget(key)["trip_details"])
        self.assertNotIn("whether those", self.prompt_of_last_reply(provider))

    def test_a_new_conversation_inherits_neither_the_question_nor_the_trip(self):
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona"), trip_details=WHEN),
                turn({}, trip_details={"confirms_party_offer": True}),
            ]
        )
        self.choose(provider)
        self.assertEqual(self.stored()["adults_offer"], 2)

        memory.clear_history(self.key)  # the "New conversation" button
        _, _, state = self.say(provider, "sim")

        self.assertIsNone(self.stored())
        self.assertIsNone(state.get("trip_details"))
        self.assertEqual(self.trip_calls(provider), 1)  # nothing was open, so nothing was read


class StaleSearchActionTests(_TripCase):
    """What the page is told when a turn changes - or takes away - the search."""

    def tab(self, provider):
        return ViewSession(
            self.user, ai_provider=provider, climate_provider=self.climate, save=False
        )

    def ready_tab(self, *later):
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                stays(adults=2, **WHEN),
                *later,
            ]
        )
        tab = self.tab(provider)
        tab.post("quero ir pra Barcelona")
        ready = tab.post("hospedagem dia 5, 3 dias, somos 2")
        return tab, ready

    def test_the_first_search_appears_as_a_card(self):
        _, ready = self.ready_tab()

        (card,) = ready.cards
        self.assertIn("checkin=2026-11-05", card["accommodation_search_url"])
        self.assertTrue(ready.retire_stays)  # (nothing is on the page yet - harmless)

    def test_a_correction_retires_the_old_button_and_brings_the_new_one(self):
        tab, _ = self.ready_tab(turn(spain(), trip_details={"start": {"day": 6}}))

        corrected = tab.post("na verdade dia 6")

        self.assertTrue(corrected.retire_stays)
        (card,) = corrected.cards
        self.assertIn("checkin=2026-11-06", card["accommodation_search_url"])
        self.assertNotIn("<<<", corrected.reply)  # the footers are not part of the reply

    def test_taking_a_detail_back_retires_the_button_and_brings_nothing(self):
        tab, _ = self.ready_tab(turn(spain(), trip_details={"cleared_fields": ["start"]}))

        cleared = tab.post("ainda não sei a data")

        self.assertTrue(cleared.retire_stays)
        self.assertEqual(cleared.cards, [])
        self.assertNotIn("<<<", cleared.reply)

    def test_a_turn_that_did_not_touch_the_search_retires_nothing(self):
        tab, _ = self.ready_tab(turn(spain()))

        thanks = tab.post("obrigado")

        self.assertFalse(thanks.retire_stays)
        self.assertEqual(thanks.cards, [])

    def test_saying_the_same_thing_again_changes_nothing_on_the_page(self):
        tab, _ = self.ready_tab(turn(spain(), trip_details={"adults": 2}))

        again = tab.post("somos 2")

        self.assertFalse(again.retire_stays)

    def test_details_that_still_leave_no_search_retire_nothing(self):
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                turn(spain(), trip_details={"adults": 2}),
            ]
        )
        tab = self.tab(provider)
        tab.post("quero ir pra Barcelona")

        partial = tab.post("somos 2")

        self.assertFalse(partial.retire_stays)  # there was no search before and there is none now
        self.assertEqual(partial.cards, [])

    def test_a_new_conversation_starts_without_a_search_or_anything_to_retire(self):
        tab, _ = self.ready_tab(turn(spain(selected_destination_name="Barcelona")))

        tab.new_conversation()
        fresh = tab.post("quero ir pra Barcelona")

        self.assertFalse(fresh.retire_stays)
        self.assertNotIn("accommodation_search_url", fresh.cards[0])  # the place, no search
        self.assertIsNone(self.stored())


class FreeformReadinessTests(_TripCase):
    """A place outside the catalog follows the same rule: no search card until
    there is a search."""

    VALENCIA = {"is_real_place": True, "name": "Valencia", "country": "Spain"}

    def test_the_card_exists_only_once_the_search_does(self):
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Valencia"), freeform_place=self.VALENCIA),
                turn(spain(), trip_details={**WHEN, "adults": 2}),
            ]
        )
        tab = ViewSession(
            self.user, ai_provider=provider, climate_provider=self.climate, save=False
        )

        chosen = tab.post("quero ir pra Valência")
        self.assertEqual(chosen.cards, [])  # the card would have been only the button
        self.assertIn("the trip's start date is missing", self.prompt_of_last_reply(provider))

        ready = tab.post("dia 5, 3 dias, somos 2")
        (card,) = ready.cards
        self.assertTrue(card["freeform"])
        self.assertIn("ss=Valencia%2C+Spain", card["accommodation_search_url"])
        self.assertIn("checkin=2026-11-05", card["accommodation_search_url"])

    def test_the_reply_to_choosing_such_a_place_ends_on_the_language_to_answer_in(self):
        provider = ScriptedProvider(
            [turn(spain(selected_destination_name="Valencia"), freeform_place=self.VALENCIA)]
        )

        self.say(provider, "quero ir pra Valência")

        prompt = self.prompt_of_last_reply(provider)
        self.assertIn("the trip's start date is missing", prompt)  # the English facts come first
        self.assertTrue(
            prompt.endswith(
                "Reply in the same language the traveler has been using in this "
                "conversation (check the history above, not just this message)."
            )
        )

    def test_the_stays_request_for_such_a_place_asks_before_it_offers(self):
        provider = ScriptedProvider(
            [
                turn(
                    spain(
                        is_accommodation_request=True, accommodation_place_name="Valencia"
                    ),
                    destination_resolution={"slug": None},
                    freeform_place=self.VALENCIA,
                )
            ]
        )

        result, _, _ = self.say(provider, "quero hospedagens em Valência")

        self.assertIsNone(result.accommodation_freeform_name)
        self.assertEqual(result.recommendations, [])
        self.assertIn("the trip's start date is missing", self.prompt_of_last_reply(provider))


class ChosenPlaceTests(_TripCase):
    """A stays request that names the place the traveler already chose is about
    that place - it is never looked up again, where the closest-match fallback
    could swap a place outside the catalog for some other one."""

    VALENCIA = {"is_real_place": True, "name": "Valencia", "country": "Spain"}
    # What the closest-match fallback would answer if it were asked.
    WRONGLY_MADRID = {"slug": "madrid-es"}

    def chose_valencia(self, *later):
        choice = turn(spain(selected_destination_name="Valencia"), freeform_place=self.VALENCIA)
        provider = ScriptedProvider([choice, *later])
        self.say(provider, "quero ir pra Valência")
        return provider

    def stays_for(self, place, **trip):
        return turn(
            spain(is_accommodation_request=True, accommodation_place_name=place),
            destination_resolution=self.WRONGLY_MADRID,
            trip_details={**WHEN, "adults": 2, **trip},
        )

    def test_a_stays_request_naming_the_chosen_place_stays_about_it(self):
        provider = self.chose_valencia(self.stays_for("Valencia"))

        result, _, _ = self.say(provider, "somos 2, dia 5, 3 dias")

        self.assertEqual(result.accommodation_freeform_name, "Valencia")
        self.assertEqual(result.recommendations, [])
        self.assertIn("a stay search for Valencia, Spain", self.prompt_of_last_reply(provider))
        self.assertNotIn("Madrid", self.prompt_of_last_reply(provider))
        self.assertNotIn("destination_resolution", provider.structured_calls)

    def test_a_booking_request_naming_the_chosen_place_does_too(self):
        booking_turn = turn(
            spain(
                is_booking_request=True,
                is_accommodation_request=True,
                accommodation_place_name="Valencia",
            ),
            destination_resolution=self.WRONGLY_MADRID,
            trip_details={**WHEN, "adults": 2},
        )
        provider = self.chose_valencia(booking_turn)

        result, _, _ = self.say(provider, "reserve para mim, somos 2, dia 5, 3 dias")

        self.assertEqual(result.accommodation_freeform_name, "Valencia")
        self.assertNotIn("destination_resolution", provider.structured_calls)

    def test_naming_the_name_a_little_differently_still_means_the_chosen_place(self):
        provider = self.chose_valencia(self.stays_for("valência"))

        result, _, _ = self.say(provider, "somos 2, dia 5, 3 dias")

        self.assertEqual(result.accommodation_freeform_name, "Valencia")

    def test_a_different_place_is_still_looked_up_as_before(self):
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                turn(
                    spain(is_accommodation_request=True, accommodation_place_name="Madrid"),
                    trip_details={**WHEN, "adults": 2},
                ),
            ]
        )
        self.say(provider, "quero ir pra Barcelona")

        result, _, _ = self.say(provider, "e hospedagem em Madrid? somos 2, dia 5, 3 dias")

        self.assert_detail_of(result, "madrid-es")
        self.assertTrue(result.is_accommodation_reply)
