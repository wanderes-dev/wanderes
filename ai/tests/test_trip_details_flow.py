"""Trip details through whole turns: what the traveler says about dates, length
and who is going becomes one resolved trip that the Booking link, its caption
and the reply's facts all share - with a model call only when there is
something to read, and the existing state-ownership protocol around the
stored record."""

from datetime import date
from unittest import mock
from urllib.parse import parse_qsl, urlparse

from ai import memory
from ai.tests.helpers import ScriptedProvider, intent
from ai.tests.test_selected_destination import _Case, barcelona_record, spain, turn
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


def query_of(url) -> list[tuple[str, str]]:
    return parse_qsl(urlparse(url).query)


class _TripCase(_Case):
    def setUp(self):
        super().setUp()
        patcher = mock.patch("ai.orchestration._today", return_value=TODAY)
        patcher.start()
        self.addCleanup(patcher.stop)

    def url_of(self, result) -> str:
        card = _recommendation_card_data(
            result.recommendations[0], detail_shown=True, trip=result.trip
        )
        return card["accommodation_search_url"]

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
                stays(),
                stays(adults=3, children=1),
                stays(child_ages=[5]),
                turn(
                    spain(),
                    trip_details={"start": {"day": 5}, "stay_length": 3, "stay_unit": "days"},
                ),
            ]
        )

        # "Quero ir pra Barcelona 10 dias" - a length with no start date
        chosen, _, _ = self.say(provider, "Quero ir pra Barcelona 10 dias")
        self.assert_detail_of(chosen, "barcelona-es")
        self.assertEqual(query_of(self.url_of(chosen)), [("ss", "Barcelona, Spain")])
        self.assertIn("Stay: 10 days (counted as 10 nights)", self.prompt_of_last_reply(provider))
        self.assertIn("no start date yet", self.prompt_of_last_reply(provider))

        # "quero hospedagens" - nobody has said who is going, so ask first
        asked, _, _ = self.say(provider, "quero hospedagens")
        self.assertEqual(asked.recommendations, [])
        self.assertIn("how many adults", self.prompt_of_last_reply(provider))

        # "3 adultos e uma criança" - never four adults; the child waits for an age
        waiting, _, state = self.say(provider, "3 adultos e uma criança")
        link = query_of(self.url_of(waiting))
        self.assertEqual(link, [("ss", "Barcelona, Spain"), ("group_adults", "3")])
        self.assertTrue(waiting.is_accommodation_reply)
        prompt = self.prompt_of_last_reply(provider)
        self.assertIn("Adults: 3.", prompt)
        self.assertIn("child is NOT included in the Booking search", prompt)
        self.assertIn("ask for the age", prompt)
        self.assertEqual(
            (state["trip_details"]["adults"], state["trip_details"]["children"]), (3, 1)
        )
        self.assertIsNone(state["trip_details"]["child_ages"])
        self.assertIn("1 child not included yet", waiting.trip.caption("Barcelona"))

        # "5 anos" - now the child goes in, with the age
        aged, _, state = self.say(provider, "5 anos")
        self.assertEqual(
            query_of(self.url_of(aged)),
            [
                ("ss", "Barcelona, Spain"),
                ("group_adults", "3"),
                ("group_children", "1"),
                ("age", "5"),
            ],
        )
        self.assertEqual(state["trip_details"]["child_ages"], [5])
        prompt = self.prompt_of_last_reply(provider)
        self.assertIn("ages 5 - included in the search", prompt)
        self.assertNotIn("ask for the age", prompt)

        # "quero ir dia 05 e ficar 3 dias" - concrete dates, the month disclosed,
        # and the link the traveler sees is the new one
        dated, _, state = self.say(provider, "quero ir dia 05 e ficar 3 dias")
        self.assertTrue(dated.is_accommodation_reply)
        self.assertEqual(
            query_of(self.url_of(dated)),
            [
                ("ss", "Barcelona, Spain"),
                ("checkin", "2026-11-05"),
                ("checkout", "2026-11-08"),
                ("group_adults", "3"),
                ("group_children", "1"),
                ("age", "5"),
            ],
        )
        prompt = self.prompt_of_last_reply(provider)
        self.assertIn("Check-in: Thursday 5 November 2026.", prompt)
        self.assertIn("the month was assumed", prompt)
        self.assertIn("Check-out: Sunday 8 November 2026 (3 nights).", prompt)
        self.assertEqual(
            (state["trip_details"]["stay_length"], state["trip_details"]["stay_unit"]),
            (3, "days"),  # the length said last replaced the earlier 10 days
        )
        self.assertNotIn("check_out", state["trip_details"])
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
        self.assertEqual(
            query_of(self.url_of(no_start)), [("ss", "Barcelona, Spain"), ("group_adults", "3")]
        )
        self.assertIsNone(self.stored()["start_date"])

        empty, _, _ = self.say(provider, "esquece a duração e o número de pessoas")
        self.assertEqual(query_of(self.url_of(empty)), [("ss", "Barcelona, Spain")])
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
        # "ficar 3 noites" and "dia 5" are a length and a day. A stays request
        # that never said who is going asks - it does not default to anyone.
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

        self.assertEqual(result.recommendations, [])  # the "who is going?" question
        self.assertIn("how many adults", self.prompt_of_last_reply(provider))
        self.assertIsNone(state["trip_details"]["adults"])
        self.assertIsNone(state["trip_details"]["children"])


class LegacyMonthTests(_TripCase):
    def test_the_intent_month_never_drives_the_booking_dates(self):
        # The combined extractor read "dia 05" as month 5. With no trip-details
        # output behind it, the link must carry no dates at all.
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
        self.assertEqual(
            query_of(self.url_of(result)), [("ss", "Barcelona, Spain"), ("group_adults", "2")]
        )
        self.assertFalse(result.trip.has_dates)


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


class StaysActionResurfacingTests(_TripCase):
    """On a turn that only carries the destination, the stays action comes
    back when - and only when - what the link carries has changed."""

    def test_a_detail_the_link_does_not_carry_leaves_the_conversation_alone(self):
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                turn(spain(), trip_details={"stay_length": 3, "stay_unit": "days"}),
                turn(spain(), trip_details={"adults": 3}),
                turn(spain(), trip_details={"children": 1}),
            ]
        )
        self.say(provider, "quero ir pra Barcelona")

        length, _, _ = self.say(provider, "me ajuda a montar um roteiro de 3 dias?")
        self.assertEqual(length.recommendations, [])  # a length with no start: link unchanged
        self.assertEqual(self.stored()["stay_length"], 3)
        self.assertIn("Stay: 3 days", self.prompt_of_last_reply(provider))

        adults, _, _ = self.say(provider, "somos 3 adultos")
        self.assertEqual(
            dict(query_of(self.url_of(adults)))["group_adults"], "3"
        )  # it carries this

        child, _, _ = self.say(provider, "e uma criança")
        self.assertEqual(child.recommendations, [])  # a child with no age: link unchanged
        self.assertIn("child is NOT included", self.prompt_of_last_reply(provider))
        self.assertIn("ask for the age", self.prompt_of_last_reply(provider))

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
                turn(spain(), trip_details={"start": {"day": 5}, "stay_length": 3}),
            ]
        )
        self.say(provider, "quero ir pra Barcelona")

        dated, _, _ = self.say(provider, "dia 5, 3 dias")

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
            [turn(spain(selected_destination_name="Barcelona")), stays(adults=2)]
        )
        self.say(provider, "quero ir pra Barcelona")

        result, _, _ = self.say(provider, "hospedagem pra 2")

        self.assertEqual(dict(query_of(self.url_of(result)))["group_adults"], "2")
        self.assertNotIn("usually travels with", self.prompt_of_last_reply(provider))


class FactsInOrdinaryRepliesTests(_TripCase):
    def test_a_reply_with_nothing_known_about_the_trip_carries_no_facts_block(self):
        provider = ScriptedProvider(
            [turn(spain(selected_destination_name="Barcelona")), turn(spain())]
        )
        self.say(provider, "quero ir pra Barcelona")
        self.assertNotIn("Trip details Wanderes holds", self.prompt_of_last_reply(provider))

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
        self.assertIn("carries exactly: 2 adults", prompt)
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
