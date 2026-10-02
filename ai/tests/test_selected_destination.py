"""A traveler who names ONE specific destination as where they're going has
already chosen: the reply is a conversation about that place, not a ranking
of its country, and the choice sticks for the follow-ups until they pick
somewhere else or reopen the question. Country-level requests ("Thailand",
"uma cidade na Espanha") stay what they always were - discovery.

The model's side of this (setting selected_destination_name, the clear flag)
is scripted; what's under test is everything the application does with it.
"""

from unittest import mock

from django.core.cache import cache
from django.test import TestCase

from ai import memory
from ai.orchestration import (
    _best_name_match,
    _catalog_destination_named,
    _drop_unoffered_bare_selection,
    _resolve_destination,
    _validate_intent,
    stream_travel_recommendation,
)
from ai.tests.helpers import (
    FixedClimateProvider,
    ScriptedProvider,
    intent,
    make_destination,
    remaining_ttl_seconds,
)
from evaluations.view_path import ViewSession
from travel.geography_aliases import _COUNTRY_ALIASES
from travel.models import Destination
from travel.services import is_catalog_country_name, is_known_country
from users.models import User

_MERGE_PATH_CALLS = ["travel_message", "climate_budget_signal", "traveler_state_clear_signal"]


def turn(intent_fields=None, *, climate=None, state_clear=None, **extra):
    return {
        "intent": intent(**(intent_fields or {})),
        "climate_budget": climate or {},
        "state_clear": state_clear or {},
        **extra,
    }


def spain(**fields):
    return {"country": "Spain", "continent": "europe", **fields}


def barcelona_record():
    return {"slug": "barcelona-es", "name": "Barcelona", "country": "Spain"}


class _Case(TestCase):
    def setUp(self):
        # Barcelona is created first on purpose: with every Spanish
        # destination tied at score 0, row order used to decide who came first.
        make_destination("barcelona-es", name="Barcelona", country="Spain", trip_type="culture")
        make_destination("madrid-es", name="Madrid", country="Spain", trip_type="culture")
        make_destination("sevilha-es", name="Seville", country="Spain", trip_type="culture")
        make_destination("bangkok-th", name="Bangkok", country="Thailand", trip_type="city")
        make_destination("phuket-th", name="Phuket", country="Thailand", trip_type="beach")
        self.climate = FixedClimateProvider()
        self.user = User.objects.create_user(email="chooser@example.com", password="x")
        self.key = memory.conversation_key(user=self.user, session_key=None)
        memory.clear_history(self.key)

    def say(self, provider, message="a message", **kwargs):
        intent_sink, state_sink = {}, {}
        result = stream_travel_recommendation(
            message,
            user=self.user,
            ai_provider=provider,
            climate_provider=self.climate,
            intent_sink=intent_sink,
            state_sink=state_sink,
            **kwargs,
        )
        "".join(result.reply_chunks)  # consuming the stream is what runs its bookkeeping
        return result, intent_sink, state_sink

    def prompt_of_last_reply(self, provider) -> str:
        return provider.stream_messages[-1][-1].content

    def slugs(self, result):
        return [r.destination.slug for r in result.recommendations]

    def selected(self):
        return memory.get_climate_budget(self.key)["selected_destination"]

    def assert_detail_of(self, result, slug):
        self.assertTrue(result.is_destination_detail)
        self.assertEqual(self.slugs(result), [slug])

    def assert_discovery(self, result):
        self.assertFalse(result.is_destination_detail)
        self.assertIsNone(result.accommodation_freeform_name)


class ExplicitChoiceRoutingTests(_Case):
    def test_a_named_city_goes_to_the_detail_path_not_a_ranking_of_its_country(self):
        provider = ScriptedProvider([turn(spain(selected_destination_name="Barcelona"))])

        result, _, state = self.say(provider, "quero ir pra Barcelona")

        self.assert_detail_of(result, "barcelona-es")
        prompt = self.prompt_of_last_reply(provider)
        self.assertIn("has chosen Barcelona, Spain", prompt)
        self.assertNotIn("top matching destinations", prompt)
        self.assertNotIn("Madrid", prompt)
        self.assertEqual(state["selected_destination"], barcelona_record())

    def test_the_named_city_wins_even_when_another_one_comes_first_in_the_table(self):
        # The original defect: Spain's destinations all tie, so "Sevilha" got
        # whichever row the database listed first - Barcelona.
        provider = ScriptedProvider([turn(spain(selected_destination_name="Seville", month=5))])

        result, _, _ = self.say(provider, "quero ir pra Sevilha em maio")

        self.assert_detail_of(result, "sevilha-es")
        self.assertIn("has chosen Seville, Spain", self.prompt_of_last_reply(provider))

    def test_row_order_never_decides_which_destination_a_name_means(self):
        # Same request against a catalog whose rows were created in the
        # opposite order: still Seville, and the control case shows the tie
        # the old behavior was at the mercy of.
        Destination.objects.all().delete()
        for slug, name in (
            ("sevilha-es", "Seville"),
            ("madrid-es", "Madrid"),
            ("barcelona-es", "Barcelona"),
        ):
            make_destination(slug, name=name, country="Spain", trip_type="culture")
        provider = ScriptedProvider(
            [turn(spain(selected_destination_name="Seville")), turn(spain())]
        )

        chosen, _, _ = self.say(provider, "quero ir pra Sevilha")
        self.assert_detail_of(chosen, "sevilha-es")

        memory.clear_history(self.key)
        control, _, _ = self.say(provider, "uma cidade na Espanha")
        self.assert_discovery(control)
        self.assertEqual(self.slugs(control)[0], "sevilha-es")  # simply the first row now

    def test_a_country_request_is_still_discovery(self):
        provider = ScriptedProvider([turn({"country": "Thailand", "continent": "asia"})])

        result, _, state = self.say(provider, "quero ir pra Tailândia")

        self.assert_discovery(result)
        self.assertCountEqual(self.slugs(result), ["bangkok-th", "phuket-th"])
        self.assertIsNone(state["selected_destination"])
        self.assertEqual(provider.structured_calls, _MERGE_PATH_CALLS)

    def test_a_region_level_request_inside_a_country_is_still_discovery(self):
        provider = ScriptedProvider([turn(spain())])

        result, _, state = self.say(provider, "quero uma cidade na Espanha")

        self.assert_discovery(result)
        self.assertCountEqual(self.slugs(result), ["barcelona-es", "madrid-es", "sevilha-es"])
        self.assertIsNone(state["selected_destination"])

    def test_a_country_the_model_wrongly_puts_in_the_selection_field_is_still_discovery(self):
        provider = ScriptedProvider(
            [
                turn(
                    {
                        "country": "Thailand",
                        "continent": "asia",
                        "selected_destination_name": "Thailand",
                    }
                )
            ]
        )

        result, intent_sink, _ = self.say(provider, "quero ir pra Tailândia")

        self.assert_discovery(result)
        self.assertIsNone(intent_sink["selected_destination_name"])

    def test_the_same_string_in_country_and_selection_is_a_region_not_a_choice(self):
        provider = ScriptedProvider(
            [
                turn(
                    {
                        "country": "Scandinavia",
                        "continent": "europe",
                        "selected_destination_name": "Scandinavia",
                    }
                )
            ]
        )

        _, intent_sink, state = self.say(provider, "quero ir pra Escandinávia")

        self.assertIsNone(intent_sink["selected_destination_name"])
        self.assertIsNone(state["selected_destination"])

    def test_only_a_recommendation_request_can_carry_a_selection(self):
        cleaned = _validate_intent(
            intent(message_type="future_intent", selected_destination_name="Barcelona")
        )

        self.assertIsNone(cleaned["selected_destination_name"])

    def test_a_message_the_model_calls_future_intent_never_becomes_a_selection(self):
        # "vou passar uns dias em Lisboa" came back as future_intent. Whatever
        # the model put in selected_destination_name, the application takes
        # the future-intent branch (it is checked before the recommendation
        # path where selections are routed) and records no choice. So a miss
        # like that one is a message_type classification problem first.
        make_destination("lisboa-pt", name="Lisbon", country="Portugal")
        provider = ScriptedProvider(
            [
                turn(
                    {
                        "message_type": "future_intent",
                        "future_destination_name": "Lisbon",
                        "country": "Portugal",
                        "selected_destination_name": "Lisbon",
                    }
                )
            ]
        )

        result, intent_sink, state = self.say(provider, "vou passar uns dias em Lisboa")

        self.assert_discovery(result)
        self.assertEqual(result.recommendations, [])
        self.assertIsNone(intent_sink["selected_destination_name"])
        self.assertIsNone(self.selected())
        self.assertEqual(provider.structured_calls, ["travel_message"])

    def test_choosing_a_catalog_city_costs_no_extra_model_calls(self):
        provider = ScriptedProvider([turn(spain(selected_destination_name="Barcelona"))])

        self.say(provider, "quero ir pra Barcelona")

        # Same three structured calls and one streamed reply a discovery turn makes.
        self.assertEqual(provider.structured_calls, _MERGE_PATH_CALLS)
        self.assertEqual((provider.reply_calls, provider.stream_calls), (0, 1))


class PlaceOutsideTheCatalogTests(_Case):
    def test_a_real_place_outside_the_catalog_gets_a_general_knowledge_reply(self):
        provider = ScriptedProvider(
            [
                turn(
                    spain(selected_destination_name="Valencia"),
                    freeform_place={"is_real_place": True, "name": "Valencia", "country": "Spain"},
                )
            ]
        )

        result, _, state = self.say(provider, "quero ir pra Valência")

        self.assertEqual(result.recommendations, [])
        self.assertFalse(result.is_destination_detail)
        self.assertEqual(result.accommodation_freeform_name, "Valencia")
        self.assertEqual(result.accommodation_freeform_country, "Spain")
        prompt = self.prompt_of_last_reply(provider)
        self.assertIn("chosen Valencia, Spain", prompt)
        self.assertIn("isn't in our curated destination dataset", prompt)
        self.assertEqual(
            state["selected_destination"], {"slug": None, "name": "Valencia", "country": "Spain"}
        )
        # One extra call - confirming the place is real - and only for a place
        # the catalog doesn't carry.
        self.assertEqual(
            provider.structured_calls, [*_MERGE_PATH_CALLS, "freeform_place_resolution"]
        )

    def test_a_place_that_is_not_real_is_not_a_selection_and_the_turn_falls_back_to_discovery(self):
        provider = ScriptedProvider([turn(spain(selected_destination_name="Atlantis"))])

        result, _, state = self.say(provider, "quero ir pra Atlantis")

        self.assert_discovery(result)
        self.assertIsNone(state["selected_destination"])

    def test_a_name_that_only_matches_in_the_middle_of_another_name_is_not_that_place(self):
        # "Lima" is inside "Kilimanjaro" - not a reason to send someone to Tanzania.
        make_destination("kilimanjaro-tz", name="Kilimanjaro", country="Tanzania")
        provider = ScriptedProvider(
            [
                turn(
                    {
                        "country": "Peru",
                        "continent": "south_america",
                        "selected_destination_name": "Lima",
                    },
                    freeform_place={"is_real_place": True, "name": "Lima", "country": "Peru"},
                )
            ]
        )

        result, _, state = self.say(provider, "quero ir pra Lima")

        self.assertEqual(result.accommodation_freeform_name, "Lima")
        self.assertNotIn("kilimanjaro-tz", self.slugs(result))
        self.assertIsNone(state["selected_destination"]["slug"])


class NoSilentSubstitutionTests(_Case):
    """A place the traveler chose is never swapped for a different one because
    something resolves it to a related destination: the catalog lookup takes
    only the same name, and the AI name-matching step is not consulted."""

    def chosen(self, message, name, *, country, freeform, resolver_slug=None):
        provider = ScriptedProvider(
            [
                turn(
                    {"country": country, "continent": "europe", "selected_destination_name": name},
                    destination_resolution={"slug": resolver_slug} if resolver_slug else {},
                    freeform_place=freeform,
                )
            ]
        )
        result, _, state = self.say(provider, message)
        return provider, result, state

    def test_a_region_is_not_replaced_by_the_catalog_city_inside_it(self):
        make_destination("firenze-it", name="Florence", country="Italy", trip_type="culture")

        provider, result, state = self.chosen(
            "quero ir pra Toscana",
            "Tuscany",
            country="Italy",
            freeform={"is_real_place": True, "name": "Tuscany", "country": "Italy"},
            resolver_slug="firenze-it",  # what the AI matcher answered when it was asked
        )

        self.assertNotIn("firenze-it", self.slugs(result))
        self.assertFalse(result.is_destination_detail)
        self.assertEqual(result.accommodation_freeform_name, "Tuscany")
        self.assertEqual(
            state["selected_destination"], {"slug": None, "name": "Tuscany", "country": "Italy"}
        )
        self.assertNotIn("destination_resolution", provider.structured_calls)

    def test_a_place_is_not_replaced_by_one_in_another_country(self):
        make_destination("porto-pt", name="Porto", country="Portugal")

        provider, result, state = self.chosen(
            "quero ir pra Valência",
            "Valencia",
            country="Spain",
            freeform={"is_real_place": True, "name": "Valencia", "country": "Spain"},
            resolver_slug="porto-pt",
        )

        self.assertNotIn("porto-pt", self.slugs(result))
        self.assertEqual(state["selected_destination"]["name"], "Valencia")
        self.assertNotIn("destination_resolution", provider.structured_calls)

    def test_a_place_is_not_replaced_by_a_longer_named_neighbour(self):
        # Prefix matches are fine for offering a suggestion link, not for a choice.
        make_destination("porto-seguro-br", name="Porto Seguro", country="Brazil")

        _, result, state = self.chosen(
            "quero ir pra Porto",
            "Porto",
            country="Portugal",
            freeform={"is_real_place": True, "name": "Porto", "country": "Portugal"},
        )

        self.assertNotIn("porto-seguro-br", self.slugs(result))
        self.assertEqual(state["selected_destination"]["slug"], None)

    def test_a_misspelled_place_reaches_the_catalog_only_through_its_standard_name(self):
        # The AI name matcher is never asked. The free-form step standardises the
        # name ("Florensa" -> "Florence"), and an exact lookup on THAT, in the
        # same country, is still the same place.
        make_destination("firenze-it", name="Florence", country="Italy")

        provider, result, state = self.chosen(
            "quero ir pra Florensa",
            "Florensa",
            country="Italy",
            freeform={"is_real_place": True, "name": "Florence", "country": "Italy"},
            resolver_slug="some-other-slug",
        )

        self.assert_detail_of(result, "firenze-it")
        self.assertEqual(state["selected_destination"]["slug"], "firenze-it")
        self.assertNotIn("destination_resolution", provider.structured_calls)
        self.assertEqual(provider.structured_calls[-1], "freeform_place_resolution")

    def test_the_standard_name_does_not_cross_into_another_country(self):
        make_destination("valencia-ve", name="Valencia", country="Venezuela")

        _, result, state = self.chosen(
            "quero ir pra Valência",
            "Valência",
            country="Spain",
            freeform={"is_real_place": True, "name": "Valencia", "country": "Spain"},
        )

        self.assertFalse(result.is_destination_detail)
        self.assertEqual(
            state["selected_destination"], {"slug": None, "name": "Valencia", "country": "Spain"}
        )

    def test_a_region_stays_free_form_even_when_the_standard_name_is_not_in_the_catalog(self):
        make_destination("firenze-it", name="Florence", country="Italy")

        _, result, state = self.chosen(
            "quero ir pra Toscana",
            "Toscana",
            country="Italy",
            freeform={"is_real_place": True, "name": "Tuscany", "country": "Italy"},
        )

        self.assertFalse(result.is_destination_detail)
        self.assertEqual(state["selected_destination"]["name"], "Tuscany")

    def test_the_same_name_still_reaches_the_catalog_detail_reply(self):
        make_destination("firenze-it", name="Florence", country="Italy")

        provider, result, state = self.chosen(
            "quero ir pra Florença",
            "Florence",
            country="Italy",
            freeform={},
        )

        self.assert_detail_of(result, "firenze-it")
        self.assertEqual(provider.structured_calls, _MERGE_PATH_CALLS)  # no extra call
        self.assertEqual(state["selected_destination"]["slug"], "firenze-it")

    def test_a_compound_catalog_entry_answers_to_each_name_it_lists(self):
        make_destination("cusco-pe", name="Cusco / Machu Picchu", country="Peru")

        _, result, _ = self.chosen("quero ir pra Cusco", "Cusco", country="Peru", freeform={})

        self.assert_detail_of(result, "cusco-pe")


class CatalogNameLookupTests(TestCase):
    def setUp(self):
        make_destination("barcelona-es", name="Barcelona", country="Spain")
        make_destination("madrid-es", name="Madrid", country="Spain")

    def test_it_finds_the_same_name_ignoring_case_and_accents(self):
        make_destination("cancun-mx", name="Cancún / Riviera Maya", country="Mexico")

        self.assertEqual(_catalog_destination_named("barcelona").slug, "barcelona-es")
        self.assertEqual(_catalog_destination_named("  BARCELONA ").slug, "barcelona-es")
        self.assertEqual(_catalog_destination_named("Cancun").slug, "cancun-mx")
        self.assertEqual(_catalog_destination_named("Riviera Maya").slug, "cancun-mx")

    def test_a_compound_entry_answers_to_every_name_it_lists_but_not_to_its_qualifier(self):
        make_destination("havai-us", name="Hawaii (Maui/Oahu)", country="USA")
        make_destination("tenerife-es", name="Tenerife / Canary Islands", country="Spain")

        self.assertEqual(_catalog_destination_named("Tenerife").slug, "tenerife-es")
        self.assertEqual(_catalog_destination_named("Canary Islands").slug, "tenerife-es")
        self.assertEqual(_catalog_destination_named("Hawaii").slug, "havai-us")
        self.assertIsNone(_catalog_destination_named("Maui"))

    def test_nothing_fuzzy_counts_as_the_same_place(self):
        make_destination("porto-seguro-br", name="Porto Seguro", country="Brazil")
        make_destination("kilimanjaro-tz", name="Kilimanjaro", country="Tanzania")
        make_destination("pai-th", name="Pai", country="Thailand")

        self.assertIsNone(_catalog_destination_named("Porto"))  # a prefix
        self.assertIsNone(_catalog_destination_named("Lima"))  # inside another name
        self.assertIsNone(_catalog_destination_named("Spain"))  # a country column match
        self.assertIsNone(_catalog_destination_named("Barcelon"))  # a typo
        self.assertEqual(_catalog_destination_named("Pai").slug, "pai-th")

    def test_two_places_with_one_name_are_told_apart_by_the_country_and_never_by_row_order(self):
        make_destination("granada-ni", name="Granada", country="Nicaragua")
        make_destination("granada-es", name="Granada", country="Spain")

        self.assertEqual(
            _catalog_destination_named("Granada", country_hint="Spain").slug, "granada-es"
        )
        self.assertEqual(
            _catalog_destination_named("Granada", country_hint="Nicaragua").slug, "granada-ni"
        )
        # No usable hint: the lowest id, the same answer every time.
        self.assertEqual(_catalog_destination_named("Granada").slug, "granada-ni")
        self.assertEqual(
            _catalog_destination_named("Granada", country_hint="Peru").slug, "granada-ni"
        )

    def test_nothing_matches_nothing(self):
        self.assertIsNone(_catalog_destination_named(""))
        self.assertIsNone(_catalog_destination_named("Atlantis"))


class SuggestionLinkResolutionTests(TestCase):
    """_resolve_destination is still the forgiving lookup the stays/suggestion
    flows rely on; only a place the traveler chose is held to an exact name."""

    def setUp(self):
        make_destination("barcelona-es", name="Barcelona", country="Spain")
        make_destination("madrid-es", name="Madrid", country="Spain")

    def test_an_exact_name_beats_a_substring_that_matches_through_the_country(self):
        # "Pai" is inside "Spain" - every Spanish destination used to match it.
        make_destination("pai-th", name="Pai", country="Thailand")

        self.assertEqual(_resolve_destination("Pai").slug, "pai-th")

    def test_an_exact_name_beats_a_longer_name_containing_it(self):
        make_destination("nice-fr", name="Nice", country="France")
        make_destination("veneza-it", name="Venice", country="Italy")

        self.assertEqual(_resolve_destination("Nice").slug, "nice-fr")

    def test_a_name_starting_with_the_text_is_still_accepted_here(self):
        make_destination("porto-seguro-br", name="Porto Seguro", country="Brazil")

        self.assertEqual(_resolve_destination("Porto").slug, "porto-seguro-br")

    def test_the_best_match_ignores_the_order_the_candidates_come_in(self):
        make_destination("pai-th", name="Pai", country="Thailand")
        everything = Destination.objects.all()

        self.assertEqual(_best_name_match(everything, "pai").slug, "pai-th")
        self.assertEqual(_best_name_match(everything.order_by("-id"), "pai").slug, "pai-th")

    def test_nothing_matches_nothing(self):
        self.assertIsNone(_resolve_destination(""))
        self.assertIsNone(_resolve_destination("Atlantis"))


class FollowUpContinuityTests(_Case):
    def choose_barcelona(self, provider):
        result, _, _ = self.say(provider, "quero ir pra Barcelona")
        self.assert_detail_of(result, "barcelona-es")

    def test_tell_me_more_stays_on_the_chosen_destination(self):
        provider = ScriptedProvider(
            [turn(spain(selected_destination_name="Barcelona")), turn(spain())]
        )
        self.choose_barcelona(provider)

        result, _, state = self.say(provider, "conte-me mais")

        self.assert_detail_of(result, "barcelona-es")
        prompt = self.prompt_of_last_reply(provider)
        self.assertIn("has chosen Barcelona, Spain", prompt)
        self.assertIn('"conte-me mais"', prompt)
        self.assertEqual(state["selected_destination"], barcelona_record())

    def test_a_follow_up_that_extracts_nothing_at_all_still_stays(self):
        provider = ScriptedProvider([turn(spain(selected_destination_name="Barcelona")), turn()])
        self.choose_barcelona(provider)

        result, _, _ = self.say(provider, "e aí, o que acha?")

        self.assert_detail_of(result, "barcelona-es")

    def test_a_cheaper_follow_up_stays_on_the_destination_and_the_budget_still_accumulates(self):
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                turn(spain(), climate={"max_cost_of_living": 2}),
            ]
        )
        self.choose_barcelona(provider)

        result, _, state = self.say(provider, "quero algo mais barato")

        self.assert_detail_of(result, "barcelona-es")
        self.assertEqual(state["max_cost_of_living"], 2)
        self.assertEqual(state["selected_destination"], barcelona_record())

    def test_an_accommodation_follow_up_stays_on_the_destination(self):
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                turn(
                    spain(
                        is_accommodation_request=True,
                        accommodation_place_name="Barcelona",
                        accommodation_party_size=4,
                    )
                ),
                turn(spain()),
            ]
        )
        self.choose_barcelona(provider)

        stays, _, _ = self.say(provider, "e hospedagem? somos 4")
        self.assert_detail_of(stays, "barcelona-es")
        self.assertEqual(stays.accommodation_party_size, 4)

        later, _, state = self.say(provider, "conte-me mais")
        self.assert_detail_of(later, "barcelona-es")
        self.assertEqual(state["selected_destination"], barcelona_record())

    def test_an_accommodation_question_without_a_place_falls_back_to_the_chosen_one(self):
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                turn(spain(is_accommodation_request=True, accommodation_place_name=None)),
            ]
        )
        self.choose_barcelona(provider)

        result, _, _ = self.say(provider, "e hospedagem?")

        self.assert_detail_of(result, "barcelona-es")

    def test_an_activity_question_keeps_the_choice_for_the_turns_after_it(self):
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                turn(spain(is_activity_question=True, activity_place_name="Barcelona")),
                turn(spain()),
            ]
        )
        self.choose_barcelona(provider)

        activity, _, _ = self.say(provider, "o que fazer lá?")
        self.assertEqual(activity.recommendations, [])  # the activity reply, as before

        later, _, state = self.say(provider, "conte-me mais")
        self.assert_detail_of(later, "barcelona-es")
        self.assertEqual(state["selected_destination"], barcelona_record())

    def test_an_explicit_change_of_mind_replaces_the_choice(self):
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                turn(spain(selected_destination_name="Madrid")),
                turn(spain()),
            ]
        )
        self.choose_barcelona(provider)

        madrid, _, state = self.say(provider, "na verdade quero Madrid")
        self.assert_detail_of(madrid, "madrid-es")
        self.assertEqual(state["selected_destination"]["slug"], "madrid-es")

        later, _, _ = self.say(provider, "conte-me mais")
        self.assert_detail_of(later, "madrid-es")  # and it stays Madrid, not Barcelona

    def test_a_passing_mention_of_another_place_does_not_replace_the_choice(self):
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                turn(spain(selected_destination_name=None)),
            ]
        )
        self.choose_barcelona(provider)

        result, _, state = self.say(provider, "e Madrid, fica longe de lá?")

        self.assert_detail_of(result, "barcelona-es")
        self.assertEqual(state["selected_destination"], barcelona_record())

    def test_reopening_the_choice_clears_it_and_goes_back_to_discovery(self):
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                turn(spain(), state_clear={"selected_destination_cleared": True}),
                turn(spain()),
            ]
        )
        self.choose_barcelona(provider)

        reopened, _, state = self.say(provider, "quero uma cidade na Espanha")
        self.assert_discovery(reopened)
        self.assertCountEqual(self.slugs(reopened), ["barcelona-es", "madrid-es", "sevilha-es"])
        self.assertIsNone(state["selected_destination"])

        later, _, _ = self.say(provider, "algo mais barato")
        self.assert_discovery(later)  # and it stays cleared

    def test_naming_a_new_place_wins_over_a_clear_in_the_same_message(self):
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                turn(
                    spain(selected_destination_name="Madrid"),
                    state_clear={"selected_destination_cleared": True},
                ),
            ]
        )
        self.choose_barcelona(provider)

        result, _, _ = self.say(provider, "outra cidade: Madrid")

        self.assert_detail_of(result, "madrid-es")

    def test_a_name_that_cannot_be_resolved_does_not_send_the_turn_to_the_old_choice(self):
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                turn(spain(selected_destination_name="Atlantis")),
            ]
        )
        self.choose_barcelona(provider)

        result, _, state = self.say(provider, "na verdade quero Atlantis")

        self.assert_discovery(result)
        self.assertEqual(
            state["selected_destination"], barcelona_record()
        )  # unchanged, just not used

    def test_a_choice_pointing_at_a_vanished_catalog_entry_is_ignored(self):
        provider = ScriptedProvider(
            [turn(spain(selected_destination_name="Barcelona")), turn(spain())]
        )
        self.choose_barcelona(provider)
        Destination.objects.filter(slug="barcelona-es").delete()

        result, _, _ = self.say(provider, "conte-me mais")

        self.assert_discovery(result)
        self.assertNotIn("barcelona-es", self.slugs(result))

    def test_a_choice_outside_the_catalog_also_sticks(self):
        provider = ScriptedProvider(
            [
                turn(
                    spain(selected_destination_name="Valencia"),
                    freeform_place={"is_real_place": True, "name": "Valencia", "country": "Spain"},
                ),
                turn(spain()),
            ]
        )
        self.say(provider, "quero ir pra Valência")

        result, _, state = self.say(provider, "conte-me mais")

        self.assertEqual(result.accommodation_freeform_name, "Valencia")
        self.assertEqual(result.recommendations, [])
        # Remembered as a record, so following up costs no resolution calls.
        self.assertEqual(provider.structured_calls[-3:], _MERGE_PATH_CALLS)
        self.assertEqual(state["selected_destination"]["name"], "Valencia")

    def test_the_choose_this_trip_button_counts_as_a_choice_for_the_follow_ups(self):
        provider = ScriptedProvider([turn(spain())])
        button, _, _ = self.say(provider, "Tell me about this", focus_destination_slug="madrid-es")
        self.assert_detail_of(button, "madrid-es")
        self.assertEqual(self.selected()["slug"], "madrid-es")

        result, _, _ = self.say(provider, "conte-me mais")

        self.assert_detail_of(result, "madrid-es")

    def test_the_choice_lives_and_dies_with_the_rest_of_the_state(self):
        provider = ScriptedProvider([turn(spain(selected_destination_name="Barcelona"))])
        self.choose_barcelona(provider)
        self.assertGreater(remaining_ttl_seconds(memory._climate_budget_key(self.key)), 0)

        memory.clear_history(self.key)  # "New conversation"

        self.assertIsNone(self.selected())

    def test_a_turn_without_state_still_honours_the_choice_it_is_given_but_remembers_nothing(self):
        # A saved conversation that doesn't own the Redis state runs stateless
        # (see ai.memory's ownership notes): the choice made in the message
        # itself works, it just isn't kept for later turns.
        history = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        provider = ScriptedProvider([turn(spain(selected_destination_name="Barcelona"))])

        result, _, state = self.say(
            provider, "quero ir pra Barcelona", history_override=history, thread_id=None
        )

        self.assert_detail_of(result, "barcelona-es")
        self.assertEqual(state, {})
        self.assertIsNone(self.selected())


class StateShapeTests(TestCase):
    def setUp(self):
        self.key = "chat-history:user:selected-shape"
        memory.clear_history(self.key)

    def test_set_unchanged_clear(self):
        record = {"slug": "barcelona-es", "name": "Barcelona", "country": "Spain"}
        state = memory.update_climate_budget(self.key, selected_destination=record)
        self.assertEqual(state["selected_destination"], record)

        state = memory.update_climate_budget(self.key, trip_type="beach")  # unrelated turn
        self.assertEqual(state["selected_destination"], record)

        state = memory.update_climate_budget(self.key, selected_destination_cleared=True)
        self.assertIsNone(state["selected_destination"])
        self.assertIsNone(memory.get_climate_budget(self.key)["selected_destination"])

    def test_a_new_value_beats_a_clear_in_the_same_turn(self):
        madrid = {"slug": "madrid-es", "name": "Madrid", "country": "Spain"}

        state = memory.resolve_state_delta(
            {**memory._NO_CLIMATE_BUDGET, "selected_destination": {"slug": "barcelona-es"}},
            selected_destination=madrid,
            selected_destination_cleared=True,
        )

        self.assertEqual(state["selected_destination"], madrid)

    def test_a_state_stored_before_the_field_existed_reads_as_not_chosen(self):
        old_shape = {
            k: v for k, v in memory._NO_CLIMATE_BUDGET.items() if k != "selected_destination"
        }
        cache.set(memory._climate_budget_key(self.key), {**old_shape, "trip_type": "beach"}, 100)

        state = memory.get_climate_budget(self.key)

        self.assertIsNone(state["selected_destination"])
        self.assertEqual(state["trip_type"], "beach")
        # ...and merging into it doesn't trip over the missing key.
        merged = memory.update_climate_budget(self.key, selected_destination={"slug": "x"})
        self.assertEqual(merged["selected_destination"], {"slug": "x"})
        self.assertEqual(merged["trip_type"], "beach")


class SavedConversationContinuityTests(TestCase):
    """The same thing through the real view with the default (saving) flow:
    turn 1 on the Redis path, later turns as history_override turns that own
    the state."""

    def setUp(self):
        make_destination("barcelona-es", name="Barcelona", country="Spain", trip_type="culture")
        make_destination("madrid-es", name="Madrid", country="Spain", trip_type="culture")
        make_destination("sevilha-es", name="Seville", country="Spain", trip_type="culture")
        self.climate = FixedClimateProvider()
        self.user = User.objects.create_user(email="saved-chooser@example.com", password="x")
        self.key = memory.conversation_key(user=self.user, session_key=None)
        memory.clear_history(self.key)

    def test_the_choice_survives_the_switch_to_override_turns(self):
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                turn(spain()),
                turn(spain(selected_destination_name="Madrid")),
                turn(spain()),
            ]
        )
        tab = ViewSession(self.user, ai_provider=provider, climate_provider=self.climate, save=True)

        first = tab.post("quero ir pra Barcelona")
        self.assertIsNone(first.view_kwargs["history_override"])  # Redis path
        self.assertEqual([r.destination.slug for r in first.recommendations], ["barcelona-es"])

        second = tab.post("conte-me mais")
        self.assertIsNotNone(second.view_kwargs["history_override"])  # override turn
        self.assertEqual([r.destination.slug for r in second.recommendations], ["barcelona-es"])
        self.assertEqual(second.state["selected_destination"]["slug"], "barcelona-es")

        third = tab.post("na verdade quero Madrid")
        self.assertEqual([r.destination.slug for r in third.recommendations], ["madrid-es"])

        fourth = tab.post("e hospedagem?")
        self.assertEqual([r.destination.slug for r in fourth.recommendations], ["madrid-es"])

    def test_a_conversation_that_lost_the_state_does_not_inherit_the_choice(self):
        provider = ScriptedProvider(
            [turn(spain(selected_destination_name="Barcelona")), turn(spain())]
        )
        tab = ViewSession(self.user, ai_provider=provider, climate_provider=self.climate, save=True)
        tab.post("quero ir pra Barcelona")
        # An unsaved tab writes the shared state: the choice is still sitting in
        # Redis, but the conversation no longer owns it.
        memory.update_climate_budget(self.key, trip_type="culture")

        second = tab.post("conte-me mais")

        self.assertEqual(second.state, {})
        self.assertCountEqual(
            [r.destination.slug for r in second.recommendations],
            ["barcelona-es", "madrid-es", "sevilha-es"],
        )


class CountryVersusPlaceValidationTests(TestCase):
    """Whether a selected name is a place or really a country is decided by
    what was written (and by the model's own country field) - never by the
    alias table, which turns "Granada" into the country Grenada."""

    def setUp(self):
        make_destination("st-georges-gd", name="St. George's", country="Grenada")
        make_destination("granada-es", name="Granada", country="Spain")
        make_destination("bangkok-th", name="Bangkok", country="Thailand")
        make_destination("lima-pe", name="Lima", country="Peru")
        make_destination("roma-it", name="Rome", country="Italy")

    def validated(self, selected, *, country=None, message_type="recommendation"):
        return _validate_intent(
            intent(message_type=message_type, selected_destination_name=selected, country=country)
        )["selected_destination_name"]

    def test_a_city_whose_name_is_also_a_country_alias_stays_a_selection(self):
        self.assertEqual(self.validated("Granada", country="Spain"), "Granada")
        self.assertEqual(self.validated("Granada"), "Granada")

    def test_the_real_country_still_is_one(self):
        self.assertIsNone(self.validated("Grenada"))
        self.assertIsNone(self.validated("Grenada", country="Grenada"))

    def test_the_model_reading_the_same_name_as_the_country_makes_it_the_country(self):
        # "Granada" with country=Grenada: the model itself took it for the country.
        self.assertIsNone(self.validated("Granada", country="Grenada"))

    def test_countries_are_still_country_level_requests(self):
        for country in ("Thailand", "Peru", "Italy"):
            with self.subTest(country=country):
                self.assertIsNone(self.validated(country))
                self.assertIsNone(self.validated(country, country=country))

    def test_a_country_written_in_another_language_is_caught_through_the_countrys_own_field(self):
        # The alias table is still how the *country field* is read.
        self.assertIsNone(self.validated("Tailândia", country="Thailand"))
        self.assertIsNone(self.validated("Itália", country="Italy"))

    def test_a_multi_country_region_the_model_put_in_both_fields_is_not_a_choice(self):
        self.assertIsNone(self.validated("Scandinavia", country="Scandinavia"))

    def test_a_region_inside_a_country_can_be_chosen_but_its_country_cannot(self):
        self.assertEqual(self.validated("Tuscany", country="Italy"), "Tuscany")
        self.assertIsNone(self.validated("Italy", country="Italy"))

    def test_an_ordinary_city_is_unaffected(self):
        self.assertEqual(self.validated("Seville", country="Spain"), "Seville")

    def test_it_is_a_rule_about_the_alias_mechanism_not_about_one_string(self):
        # A fictional collision: a place name that the alias table maps to a country.
        make_destination("narnia-nr", name="Cair Paravel", country="Narnia")
        with mock.patch.dict(_COUNTRY_ALIASES, {"springfield": "Narnia"}):
            self.assertEqual(self.validated("Springfield", country="Spain"), "Springfield")
            self.assertIsNone(self.validated("Narnia"))

    def test_a_non_recommendation_message_still_carries_no_selection(self):
        self.assertIsNone(self.validated("Granada", country="Spain", message_type="future_intent"))

    def test_through_the_pipeline_granada_in_spain_is_the_destination_chosen(self):
        user = User.objects.create_user(email="granada@example.com", password="x")
        provider = ScriptedProvider([turn(spain(selected_destination_name="Granada"))])

        result = stream_travel_recommendation(
            "quero ir pra Granada",
            user=user,
            ai_provider=provider,
            climate_provider=FixedClimateProvider(),
        )
        "".join(result.reply_chunks)

        self.assertTrue(result.is_destination_detail)
        self.assertEqual([r.destination.slug for r in result.recommendations], ["granada-es"])

    def test_through_the_pipeline_grenada_the_country_is_still_discovery(self):
        user = User.objects.create_user(email="grenada@example.com", password="x")
        provider = ScriptedProvider(
            [
                turn(
                    {
                        "country": "Grenada",
                        "continent": "north_america",
                        "selected_destination_name": "Grenada",
                    }
                )
            ]
        )

        result = stream_travel_recommendation(
            "quero ir pra Grenada",
            user=user,
            ai_provider=provider,
            climate_provider=FixedClimateProvider(),
        )
        "".join(result.reply_chunks)

        self.assertFalse(result.is_destination_detail)
        self.assertEqual([r.destination.slug for r in result.recommendations], ["st-georges-gd"])


class CatalogCountryNameTests(TestCase):
    def setUp(self):
        make_destination("bangkok-th", name="Bangkok", country="Thailand")

    def test_matches_a_country_as_written_ignoring_case_and_padding(self):
        self.assertTrue(is_catalog_country_name("Thailand"))
        self.assertTrue(is_catalog_country_name("  thailand "))

    def test_does_not_go_through_the_alias_table(self):
        self.assertFalse(is_catalog_country_name("Tailândia"))
        self.assertTrue(is_known_country("Tailândia"))  # the alias-aware check still does

    def test_rejects_places_and_blanks(self):
        self.assertFalse(is_catalog_country_name("Bangkok"))
        self.assertFalse(is_catalog_country_name(""))
        self.assertFalse(is_catalog_country_name(None))


class BareNameGuardTests(_Case):
    """A bare place name picks a destination only as the answer to options the
    assistant just presented; the model selects any bare name, so the history
    decides."""

    OPTIONS = [
        {"role": "user", "content": "quero um lugar quente pra relaxar"},
        {"role": "assistant", "content": "Boas opções: Bali, Phuket e Cancún. Qual te interessa?"},
    ]

    def kept(self, message, history=None, name="Bali"):
        intent_like = {"selected_destination_name": name}
        _drop_unoffered_bare_selection(message, intent_like, history)
        return intent_like["selected_destination_name"]

    def test_a_bare_name_with_nothing_presented_is_just_a_mention(self):
        self.assertIsNone(self.kept("Bali"))
        self.assertIsNone(self.kept("Bali", history=[]))

    def test_a_bare_name_among_the_options_just_presented_is_a_choice(self):
        self.assertEqual(self.kept("Bali", self.OPTIONS), "Bali")
        self.assertEqual(self.kept("Phuket", self.OPTIONS, name="Phuket"), "Phuket")

    def test_a_bare_name_the_reply_never_offered_is_not(self):
        self.assertIsNone(self.kept("Lisboa", self.OPTIONS, name="Lisbon"))

    def test_only_the_latest_reply_counts(self):
        history = [
            {"role": "assistant", "content": "Que tal Bali?"},
            {"role": "user", "content": "hmm"},
            {"role": "assistant", "content": "Ou então Lisboa e Porto."},
        ]

        self.assertIsNone(self.kept("Bali", history))

    def test_case_and_accents_do_not_matter(self):
        history = [{"role": "assistant", "content": "Que tal Sevilha ou Granada?"}]

        self.assertEqual(self.kept("sevilha", history, name="Seville"), "Seville")
        self.assertEqual(self.kept("SEVILHÁ!", history, name="Seville"), "Seville")

    def test_the_models_english_name_can_match_the_reply_too(self):
        history = [{"role": "assistant", "content": "Lisbon and Porto are both great."}]

        self.assertEqual(self.kept("Lisboa", history, name="Lisbon"), "Lisbon")

    def test_articles_and_politeness_do_not_make_it_a_statement(self):
        self.assertIsNone(self.kept("o Bali"))
        self.assertIsNone(self.kept("Bali, por favor"))
        self.assertEqual(self.kept("o Bali", self.OPTIONS), "Bali")

    def test_a_two_word_place_name_is_still_bare(self):
        self.assertIsNone(self.kept("Hoi An", name="Hoi An"))
        self.assertEqual(
            self.kept("Hoi An", [{"role": "assistant", "content": "Hoi An?"}], name="Hoi An"),
            "Hoi An",
        )

    def test_three_words_is_already_a_statement(self):
        # Doubt goes toward keeping the selection: "outra cidade: Madrid" must
        # not be mistaken for a bare mention.
        self.assertEqual(self.kept("outra cidade: Madrid", name="Madrid"), "Madrid")
        self.assertEqual(self.kept("na verdade Madrid", name="Madrid"), "Madrid")
        self.assertEqual(self.kept("Rio de Janeiro", name="Rio de Janeiro"), "Rio de Janeiro")

    def test_a_statement_of_choice_needs_no_context(self):
        for message in (
            "quero Bali",
            "vou pra Bali",
            "I want Bali",
            "quero ir pra Bali",
            "vamos de Bali",
        ):
            with self.subTest(message=message):
                self.assertEqual(self.kept(message), "Bali")

    def test_a_longer_message_is_never_bare(self):
        self.assertEqual(self.kept("Bali parece uma boa pedida pra mim"), "Bali")

    def test_nothing_selected_nothing_to_do(self):
        self.assertIsNone(self.kept("Bali", name=None))

    def test_through_the_pipeline_a_bare_name_without_context_is_not_a_choice(self):
        make_destination("bali-id", name="Bali", country="Indonesia", trip_type="beach")
        provider = ScriptedProvider(
            [turn({"country": "Indonesia", "selected_destination_name": "Bali"})]
        )

        result, intent_sink, state = self.say(provider, "Bali")

        self.assert_discovery(result)
        self.assertIsNone(intent_sink["selected_destination_name"])
        self.assertIsNone(state["selected_destination"])

    def test_through_the_pipeline_a_bare_name_among_the_options_is_the_choice(self):
        make_destination("bali-id", name="Bali", country="Indonesia", trip_type="beach")
        provider = ScriptedProvider(
            [turn({"country": "Indonesia", "selected_destination_name": "Bali"})]
        )

        result, _, _ = self.say(provider, "Bali", history_override=self.OPTIONS, thread_id=None)

        self.assert_detail_of(result, "bali-id")
