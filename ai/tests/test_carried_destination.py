"""The traveler's current message decides what the reply is about; a chosen
destination that is only carried from earlier turns is context for that
answer, not an instruction to describe the place again.

The turn that makes the choice still gets the rich destination reply and its
card. Every later turn that merely carries the choice is led by the message:
no climate line, no video offer, no closing-question instruction, no card and
no selection event.
"""

from django.test import TestCase

from ai import memory
from ai.orchestration import _build_carried_destination_messages, _same_place
from ai.prompts import SYSTEM_PROMPT
from ai.tests.helpers import FixedClimateProvider, ScriptedProvider, make_destination
from ai.tests.test_selected_destination import _Case, barcelona_record, spain, turn
from analytics.models import Event
from evaluations.view_path import ViewSession
from travel.models import CountryEntryRequirement, Destination
from users.models import TravelerProfile, User

_MERGE_PATH_CALLS = ["travel_message", "climate_budget_signal", "traveler_state_clear_signal"]


class CountingClimate(FixedClimateProvider):
    def __init__(self):
        self.lookups = 0

    def get_monthly_climate(self, **kwargs):
        self.lookups += 1
        return super().get_monthly_climate(**kwargs)


class _CarriedCase(_Case):
    def setUp(self):
        super().setUp()
        self.climate = CountingClimate()
        Destination.objects.filter(slug="barcelona-es").update(
            short_description="Catalan city of modernist architecture.",
            points_of_interest=["Sagrada Família", "Park Güell"],
            best_season="May-Jun / Sep",
            cost_of_living=3,
        )
        CountryEntryRequirement.objects.create(
            country="Spain", videos=[["https://www.youtube.com/watch?v=abc123", "EN"]]
        )

    def choose_barcelona(self, provider):
        result, _, _ = self.say(provider, "quero ir pra Barcelona")
        self.assert_detail_of(result, "barcelona-es")
        return result


class FreshVersusCarriedReplyTests(_CarriedCase):
    def test_the_turn_that_makes_the_choice_still_gets_the_rich_reply_and_its_card(self):
        provider = ScriptedProvider([turn(spain(selected_destination_name="Barcelona"))])

        result = self.choose_barcelona(provider)

        prompt = self.prompt_of_last_reply(provider)
        self.assertTrue(result.is_destination_detail)
        self.assertFalse(result.is_accommodation_reply)
        self.assertIn("has chosen Barcelona, Spain", prompt)
        self.assertIn("Points of interest: Sagrada Família, Park Güell", prompt)
        self.assertIn("Current typical avg high", prompt)
        self.assertIn("A real video is on file for: Spain", prompt)
        self.assertIn("invite a real follow-up question", prompt)

    def test_a_later_turn_is_led_by_the_message_and_drops_the_description_pressure(self):
        provider = ScriptedProvider(
            [turn(spain(selected_destination_name="Barcelona")), turn(spain())]
        )
        self.choose_barcelona(provider)

        result, _, _ = self.say(provider, "continua com a data errada")

        prompt = self.prompt_of_last_reply(provider)
        self.assert_carried_on(result, provider, "Barcelona, Spain")
        self.assertIn('"continua com a data errada"', prompt)
        self.assertIn("Answer what they just said, directly and first", prompt)
        # Facts stay available as reference, but nothing pushes them.
        self.assertIn("Reference facts about it", prompt)
        self.assertIn("only when they help answer, not a list to recite", prompt)
        self.assertNotIn("Current typical avg high", prompt)
        self.assertNotIn("A real video is on file", prompt)
        self.assertNotIn("follow-up question", prompt)
        self.assertNotIn("bring the description", prompt)
        self.assertIn("Don't close with a generic question or an offer", prompt)

    def test_the_carried_reply_is_told_not_to_invent_prices_dates_travelers_or_link_state(self):
        provider = ScriptedProvider(
            [turn(spain(selected_destination_name="Barcelona")), turn(spain())]
        )
        self.choose_barcelona(provider)

        self.say(provider, "quanto custa?")

        prompt = self.prompt_of_last_reply(provider)
        self.assertIn("Never invent prices, availability, dates, numbers of travelers", prompt)
        self.assertIn("what any search link contains", prompt)
        self.assertIn("exist only as the trip details listed above", prompt)
        self.assertIn("never say one was set, changed or corrected unless they say so", prompt)
        self.assertIn("You can't change a booking page the traveler already opened", prompt)
        self.assertIn("nor typical price ranges", prompt)
        self.assertIn("Without such a list you can't see what a link carried", prompt)
        self.assertIn("don't explain, defend or deny it", prompt)
        self.assertIn("we hold no verified prices", prompt)
        self.assertIn("Cost of living tier: Medium (3 on a 1-5 scale", prompt)
        self.assertNotIn("€", prompt)

    def test_the_system_prompt_carries_the_same_rule_for_every_reply(self):
        self.assertIn("Never invent destinations, prices, availability", SYSTEM_PROMPT)
        self.assertIn(
            "Never state or imply that a date, a number of travelers, a booking, or what a "
            "search link contains has been set, changed or fixed",
            " ".join(SYSTEM_PROMPT.split()),
        )
        flat = " ".join(SYSTEM_PROMPT.split())
        self.assertIn("a list of trip details is given, it is the only source", flat)
        self.assertIn("you cannot change a page the traveler already opened", flat)
        self.assertIn("Without such a list you can't see what a search link carried", flat)

    def test_the_model_restating_the_same_place_does_not_make_it_a_new_choice(self):
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                turn(spain(selected_destination_name="Barcelona")),  # restated on a follow-up
            ]
        )
        self.choose_barcelona(provider)

        result, _, _ = self.say(provider, "continua com a data errada")

        self.assert_carried_on(result, provider, "Barcelona, Spain")

    def test_naming_a_different_place_is_a_new_choice_and_gets_the_rich_reply(self):
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                turn(spain(selected_destination_name="Madrid")),
            ]
        )
        self.choose_barcelona(provider)

        result, _, _ = self.say(provider, "na verdade quero Madrid")

        self.assert_detail_of(result, "madrid-es")
        self.assertIn("has chosen Madrid, Spain", self.prompt_of_last_reply(provider))

    def test_with_no_state_to_compare_against_a_choice_in_the_message_counts_as_made_now(self):
        history = [{"role": "user", "content": "oi"}, {"role": "assistant", "content": "olá"}]
        provider = ScriptedProvider([turn(spain(selected_destination_name="Barcelona"))])

        result, _, _ = self.say(
            provider, "quero ir pra Barcelona", history_override=history, thread_id=None
        )

        self.assert_detail_of(result, "barcelona-es")
        self.assertIn("has chosen Barcelona, Spain", self.prompt_of_last_reply(provider))

    def test_the_button_is_still_a_fresh_choice(self):
        provider = ScriptedProvider([turn(spain())])

        result, _, _ = self.say(provider, "Tell me about this", focus_destination_slug="madrid-es")

        self.assert_detail_of(result, "madrid-es")
        self.assertIn("Choose this trip", self.prompt_of_last_reply(provider))

    def test_a_place_outside_the_catalog_is_fresh_once_and_then_carried(self):
        provider = ScriptedProvider(
            [
                turn(
                    spain(selected_destination_name="Valencia"),
                    freeform_place={"is_real_place": True, "name": "Valencia", "country": "Spain"},
                ),
                turn(spain()),
            ]
        )

        first, _, _ = self.say(provider, "quero ir pra Valência")
        second, _, _ = self.say(provider, "quanto custa?")

        self.assertEqual(first.accommodation_freeform_name, "Valencia")  # card for the choice
        self.assert_carried_on(second, provider, "Valencia, Spain")
        self.assertIn("no verified facts", self.prompt_of_last_reply(provider))

    def test_the_explicit_accommodation_request_still_gets_its_action(self):
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                turn(
                    spain(is_accommodation_request=True, accommodation_place_name="Barcelona"),
                    trip_details={"adults": 2},
                ),
            ]
        )
        self.choose_barcelona(provider)

        stays, _, _ = self.say(provider, "e hospedagem? somos 2")

        self.assert_detail_of(stays, "barcelona-es")
        self.assertEqual(stays.trip.adults, 2)
        self.assertTrue(stays.is_accommodation_reply)

    def test_a_stays_reply_is_a_search_action_not_a_description_of_the_place(self):
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                turn(
                    spain(is_accommodation_request=True, accommodation_place_name="Barcelona"),
                    trip_details={"adults": 2},
                ),
            ]
        )
        self.choose_barcelona(provider)

        self.say(provider, "e hospedagem? somos 2")

        prompt = self.prompt_of_last_reply(provider)
        self.assertIn("working on a stay search for Barcelona, Spain", prompt)
        self.assertIn("Do NOT write a guide", prompt)
        self.assertIn("Adults: 2.", prompt)
        # Nothing to describe the place with: no description, no points of
        # interest, no weather, no video.
        self.assertNotIn("Points of interest", prompt)
        self.assertNotIn("Description:", prompt)
        self.assertNotIn("Current typical avg high", prompt)
        self.assertNotIn("A real video is on file", prompt)
        self.assertNotIn("you may offer to show it", prompt)


class OffTopicLabelledFollowUpTests(_CarriedCase):
    """The intent call sometimes files a follow-up on the trip ("quanto
    custa?", "obrigado") as off_topic; with a destination chosen it still
    gets the grounded, message-first prompt, not the generic off-topic one."""

    def test_an_off_topic_turn_after_a_choice_uses_the_carried_prompt(self):
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                turn(spain(message_type="off_topic")),
            ]
        )
        self.choose_barcelona(provider)

        result, _, _ = self.say(provider, "quanto custa?")

        self.assert_carried_on(result, provider, "Barcelona, Spain")
        prompt = self.prompt_of_last_reply(provider)
        self.assertIn("nor typical price ranges", prompt)
        self.assertIn('"quanto custa?"', prompt)
        self.assertNotIn("Current typical avg high", prompt)

    def test_an_off_topic_turn_with_no_choice_keeps_the_generic_reply(self):
        provider = ScriptedProvider([turn(spain(message_type="off_topic"))])

        result, _, _ = self.say(provider, "você é uma IA?")

        self.assertEqual(result.recommendations, [])
        prompt = self.prompt_of_last_reply(provider)
        self.assertNotIn("is already the traveler's chosen destination", prompt)
        self.assertIn("Answer naturally, per your instructions", prompt)
        self.assertIn("an exact current price or a typical price range", prompt)

    def test_a_choice_whose_catalog_entry_is_gone_falls_back_to_the_generic_reply(self):
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                turn(spain(message_type="off_topic")),
            ]
        )
        self.choose_barcelona(provider)
        Destination.objects.filter(slug="barcelona-es").delete()

        self.say(provider, "obrigado")

        prompt = self.prompt_of_last_reply(provider)
        self.assertNotIn("is already the traveler's chosen destination", prompt)
        self.assertIn("Answer naturally, per your instructions", prompt)


class CarriedCostTests(_CarriedCase):
    def test_a_carried_turn_makes_no_climate_lookup_and_no_extra_model_call(self):
        provider = ScriptedProvider(
            [turn(spain(selected_destination_name="Barcelona")), turn(spain())]
        )
        self.choose_barcelona(provider)
        lookups_after_the_choice = self.climate.lookups
        calls_after_the_choice = len(provider.structured_calls)

        self.say(provider, "obrigado")

        self.assertEqual(lookups_after_the_choice, 1)  # the rich reply's climate line
        self.assertEqual(self.climate.lookups, 1)  # the carried one needs none
        self.assertEqual(provider.structured_calls[calls_after_the_choice:], _MERGE_PATH_CALLS)
        self.assertEqual((provider.reply_calls, provider.stream_calls), (0, 2))

    def test_the_profile_does_not_leak_into_a_carried_reply(self):
        # "usually travels with 4 people" made a reply talk about a group the
        # traveler never mentioned; the rich reply keeps the note, the carried
        # one has no use for it.
        TravelerProfile.objects.create(user=self.user, travelers_count=4, home_country="Brazil")
        provider = ScriptedProvider(
            [turn(spain(selected_destination_name="Barcelona")), turn(spain())]
        )
        self.choose_barcelona(provider)
        self.assertIn("usually travels with 4 people", self.prompt_of_last_reply(provider))

        self.say(provider, "por que colocou 4 pessoas?")

        self.assertNotIn("usually travels with", self.prompt_of_last_reply(provider))


class SamePlaceTests(TestCase):
    def test_the_same_catalog_entry_is_the_same_place(self):
        self.assertTrue(_same_place(barcelona_record(), dict(barcelona_record(), name="Barna")))
        self.assertFalse(_same_place(barcelona_record(), {**barcelona_record(), "slug": "x"}))

    def test_a_place_outside_the_catalog_is_compared_by_name_and_country(self):
        valencia = {"slug": None, "name": "Valencia", "country": "Spain"}

        self.assertTrue(
            _same_place(valencia, {"slug": None, "name": "valência", "country": "spain"})
        )
        self.assertFalse(_same_place(valencia, {"slug": None, "name": "Valencia", "country": "X"}))
        self.assertFalse(_same_place(valencia, barcelona_record()))

    def test_nothing_is_the_same_as_nothing(self):
        self.assertFalse(_same_place(None, None))
        self.assertFalse(_same_place(barcelona_record(), None))


class CarriedPromptBuilderTests(TestCase):
    def test_a_catalog_place_is_described_as_reference_and_a_free_form_one_as_unverified(self):
        destination = make_destination(
            "x-xx", name="Xville", country="Xland", short_description="A town.", cost_of_living=2
        )

        with_facts = _build_carried_destination_messages(
            "oi", {"name": "Xville", "country": "Xland", "slug": "x-xx"}, destination, []
        )[-1].content
        without = _build_carried_destination_messages(
            "oi", {"name": "Yburg", "country": "", "slug": None}, None, []
        )[-1].content

        self.assertIn("Xville, Xland is already the traveler's chosen destination", with_facts)
        self.assertIn("- Description: A town.", with_facts)
        self.assertIn("Yburg is already the traveler's chosen destination", without)
        self.assertIn("we hold no verified facts", without)
        self.assertNotIn("- Description:", without)

    def test_it_asks_for_the_language_of_the_conversation_and_hides_the_interface(self):
        content = _build_carried_destination_messages(
            "oi", {"name": "Yburg", "country": "", "slug": None}, None, []
        )[-1].content

        self.assertIn("Reply in the same language the traveler has been using", content)
        self.assertIn("Do not mention saving this as a trip", content)


class CardAndAnalyticsTests(TestCase):
    """Through the real view: a choice records one destination_selected event
    and a card; later turns that only carry it record nothing."""

    def setUp(self):
        make_destination("barcelona-es", name="Barcelona", country="Spain", trip_type="culture")
        make_destination("madrid-es", name="Madrid", country="Spain", trip_type="culture")
        self.climate = FixedClimateProvider()
        self.user = User.objects.create_user(email="analytics@example.com", password="x")
        memory.clear_history(memory.conversation_key(user=self.user, session_key=None))

    def selected_events(self):
        return Event.objects.filter(event_type="destination_selected").count()

    def test_only_the_turn_that_chooses_records_a_selection_and_a_card(self):
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                turn(spain(selected_destination_name="Barcelona")),
                turn(spain()),
                turn(spain(selected_destination_name="Madrid")),
                turn(spain()),
            ]
        )
        tab = ViewSession(self.user, ai_provider=provider, climate_provider=self.climate, save=True)

        chosen = tab.post("quero ir pra Barcelona")
        self.assertEqual([r.destination.slug for r in chosen.recommendations], ["barcelona-es"])
        self.assertEqual(self.selected_events(), 1)

        for message in ("continua com a data errada", "por que colocou 4 pessoas?"):
            carried = tab.post(message)
            self.assertEqual(carried.recommendations, [])  # no card re-emitted
            self.assertEqual(self.selected_events(), 1)  # and no new selection event

        replaced = tab.post("na verdade quero Madrid")
        self.assertEqual([r.destination.slug for r in replaced.recommendations], ["madrid-es"])
        self.assertEqual(self.selected_events(), 2)

        tab.post("obrigado")
        self.assertEqual(self.selected_events(), 2)

    def test_a_stays_request_reuses_the_chosen_place_and_records_no_selection(self):
        def stays(place):
            return turn(
                spain(is_accommodation_request=True, accommodation_place_name=place),
                trip_details={"adults": 2},
            )

        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                turn(spain()),
                stays("Barcelona"),
                stays("Barcelona"),
                turn(spain(selected_destination_name="Madrid")),
                stays("Madrid"),
            ]
        )
        tab = ViewSession(self.user, ai_provider=provider, climate_provider=self.climate, save=True)

        tab.post("quero ir pra Barcelona")
        self.assertEqual(self.selected_events(), 1)

        tab.post("o que fazer lá?")
        self.assertEqual(self.selected_events(), 1)

        first_stays = tab.post("e hospedagem? somos 2")
        # The stays reply still carries its card and action ...
        slugs = [r.destination.slug for r in first_stays.recommendations]
        self.assertEqual(slugs, ["barcelona-es"])
        # ... but reusing the chosen place for a stays search is not a selection.
        self.assertEqual(self.selected_events(), 1)

        tab.post("quais bairros são melhores?")
        self.assertEqual(self.selected_events(), 1)

        tab.post("na verdade quero Madrid")
        self.assertEqual(self.selected_events(), 2)

        tab.post("e hospedagem em Madrid?")
        self.assertEqual(self.selected_events(), 2)
        # A stays reply is not a new recommendation either.
        self.assertFalse(Event.objects.filter(event_type="recommendation_generated").exists())
