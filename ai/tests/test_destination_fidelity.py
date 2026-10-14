"""A place the traveler names is the place everything is done for.

A stays or booking request, a trip saved for someday and a visit reported in the chat all
start from a name. If the catalog does not carry that name, the chat does not reach for a
nearby or similarly named entry: "Faro" is not the Faroe Islands and "Coimbra" is not Porto.
The place is resolved exactly like one the traveler chooses (`_resolve_selected_destination`),
so the search link, the saved trip and the registered visit are for what they said.

The model's side - which place name it extracts, what the closest-match call WOULD have
answered, whether the free-form step thinks a place is real - is scripted; what is under test
is everything the application does with it."""

from unittest import mock

from django.test import TestCase

from ai.orchestration import _named_place
from ai.tests.helpers import ScriptedProvider, make_destination
from ai.tests.test_selected_destination import WHEN, turn
from ai.tests.test_trip_details_flow import _TripCase, query_of
from evaluations.view_path import ViewSession
from travel.models import Destination
from trips.models import Feedback, TravelHistoryEntry, Trip

# What the closest-match model call answered in live runs when it was asked about a place the
# catalog does not carry: the nearest big city.
NEAREST = {
    "Faro": {"slug": "ilhas-faroe"},
    "Coimbra": {"slug": "porto-pt"},
    "Aveiro": {"slug": "porto-pt"},
    "Braga": {"slug": "porto-pt"},
    "Viseu": {"slug": "porto-pt"},
}


def portugal(**fields):
    return {"country": "Portugal", "continent": "europe", **fields}


def real_place(name, country):
    """What the free-form step answers for a real place."""
    return {"is_real_place": True, "name": name, "country": country}


def stays_in(place, *, country="Portugal", **extra):
    """A turn the intent call files as a stays request for `place`, with the trip components
    the trip-details call returns for it."""
    script = {
        "trip_details": {**WHEN, "adults": 2},
        "destination_resolution": NEAREST.get(place, {}),
        "freeform_place": real_place(place, country),
        **extra,
    }
    return turn(
        portugal(country=country, is_accommodation_request=True, accommodation_place_name=place),
        **script,
    )


class _PortugalCase(_TripCase):
    """The catalog holds Porto, Lisbon, the Faroe Islands and Shanghai - and none of Faro,
    Coimbra, Aveiro, Braga or Viseu."""

    def setUp(self):
        super().setUp()
        make_destination("porto-pt", name="Porto", country="Portugal", trip_type="city")
        make_destination("lisboa-pt", name="Lisbon", country="Portugal", trip_type="city")
        make_destination(
            "ilhas-faroe", name="Faroe Islands", country="Faroe Islands", trip_type="nature"
        )
        make_destination("xangai-cn", name="Shanghai", country="China", trip_type="city")

    def tab(self, provider):
        return ViewSession(
            self.user, ai_provider=provider, climate_provider=self.climate, save=False
        )

    def search_term(self, card):
        return dict(query_of(card["accommodation_search_url"]))["ss"]

    def assert_search_for(self, card, place, country, *, catalog_slug=None):
        """The card, its caption and the Booking search term are all for exactly this place."""
        self.assertEqual(card["name"], place)
        self.assertEqual(self.search_term(card), f"{place}, {country}")
        self.assertTrue(card["accommodation_caption"].startswith(f"Booking search: {place} "))
        if catalog_slug is None:
            self.assertTrue(card["freeform"])
            self.assertNotIn("slug", card)
        else:
            self.assertEqual(card["slug"], catalog_slug)


# --- 1. a stays request ---------------------------------------------------------------------


class StaysRequestTests(_PortugalCase):
    def stay_for(self, place, message):
        provider = ScriptedProvider([stays_in(place)])
        shown = self.tab(provider).post(message)
        (card,) = shown.cards
        self.assertEqual(shown.recommendations, [])  # no catalog destination stands in
        # The closest-match call is not made at all, whatever it would have answered.
        self.assertNotIn("destination_resolution", provider.structured_calls)
        self.assertEqual(provider.structured_calls.count("freeform_place_resolution"), 1)
        return provider, card

    def test_faro_in_portugal_stays_faro_and_never_becomes_the_faroe_islands(self):
        _, card = self.stay_for("Faro", "Faro, Portugal de 20 a 23 de dezembro, somos quatro")

        self.assert_search_for(card, "Faro", "Portugal")
        self.assertNotIn("Faroe", card["accommodation_search_url"])

    def test_coimbra_stays_coimbra_and_never_becomes_porto(self):
        _, card = self.stay_for("Coimbra", "Coimbra de 5 a 8 de dezembro, dois adultos")

        self.assert_search_for(card, "Coimbra", "Portugal")

    def test_aveiro_stays_aveiro_and_never_becomes_porto(self):
        _, card = self.stay_for("Aveiro", "Aveiro de 5 a 8 de dezembro, dois adultos")

        self.assert_search_for(card, "Aveiro", "Portugal")

    def test_other_places_the_catalog_lacks_stay_what_they_are(self):
        for place in ("Braga", "Viseu"):
            with self.subTest(place=place):
                _, card = self.stay_for(place, f"hospedagem em {place}, dia 5, 3 dias, somos 2")

                self.assert_search_for(card, place, "Portugal")

    def test_the_prompt_and_the_caption_are_for_the_named_place_too(self):
        provider, card = self.stay_for("Coimbra", "hospedagem em Coimbra, dia 5, 3 dias, somos 2")

        prompt = self.prompt_of_last_reply(provider)
        self.assertIn("a stay search for Coimbra, Portugal", prompt)
        self.assertNotIn("Porto", prompt)
        self.assertEqual(
            card["accommodation_caption"],
            "Booking search: Coimbra · 5 Nov 2026 – 8 Nov 2026 (3 nights), month assumed"
            " · 2 adults",
        )

    def test_the_place_the_traveler_chose_in_that_message_is_remembered_as_that_place(self):
        provider = ScriptedProvider(
            [
                turn(
                    portugal(
                        is_accommodation_request=True,
                        accommodation_place_name="Coimbra",
                        selected_destination_name="Coimbra",
                    ),
                    trip_details={**WHEN, "adults": 2},
                    destination_resolution=NEAREST["Coimbra"],
                    freeform_place=real_place("Coimbra", "Portugal"),
                )
            ]
        )

        self.tab(provider).post("quero ir pra Coimbra, dia 5, 3 dias, somos 2")

        self.assertEqual(
            self.selected(), {"slug": None, "name": "Coimbra", "country": "Portugal"}
        )

    def test_the_next_message_stays_on_the_place_instead_of_looking_it_up_again(self):
        # The model carries the name forward on a follow-up; with the choice remembered the
        # place is not resolved a second time, and so cannot come out as something else.
        first = turn(
            portugal(
                is_accommodation_request=True,
                accommodation_place_name="Coimbra",
                selected_destination_name="Coimbra",
            ),
            trip_details={**WHEN, "adults": 2},
            destination_resolution=NEAREST["Coimbra"],
            freeform_place=real_place("Coimbra", "Portugal"),
        )
        second = turn(
            portugal(is_accommodation_request=True, accommodation_place_name="Coimbra"),
            trip_details={"rooms": 2},
            destination_resolution=NEAREST["Coimbra"],
        )
        provider = ScriptedProvider([first, second])
        tab = self.tab(provider)
        tab.post("Coimbra, dia 5, 3 dias, somos 2")

        again = tab.post("quero dois quartos")

        (card,) = again.cards
        self.assert_search_for(card, "Coimbra", "Portugal")
        self.assertEqual(dict(query_of(card["accommodation_search_url"]))["no_rooms"], "2")
        self.assertEqual(provider.structured_calls.count("freeform_place_resolution"), 1)
        self.assertNotIn("destination_resolution", provider.structured_calls)


class CatalogPlacesStayCatalogPlacesTests(_PortugalCase):
    """The strict lookup must not cost the places the catalog does carry."""

    def card_for(self, place, country, **extra):
        provider = ScriptedProvider(
            [
                turn(
                    portugal(
                        country=country,
                        is_accommodation_request=True,
                        accommodation_place_name=place,
                    ),
                    trip_details={**WHEN, "adults": 2},
                    **extra,
                )
            ]
        )
        shown = self.tab(provider).post(f"hospedagem em {place}, dia 5, 3 dias, somos 2")
        (card,) = shown.cards
        return provider, shown, card

    def test_a_catalog_place_by_its_own_name_gets_its_catalog_card_with_no_extra_call(self):
        for place, slug in (("Porto", "porto-pt"), ("Lisbon", "lisboa-pt")):
            with self.subTest(place=place):
                provider, shown, card = self.card_for(place, "Portugal")

                self.assert_search_for(card, place, "Portugal", catalog_slug=slug)
                self.assertTrue(shown.recommendations[0].destination.slug, slug)
                self.assertNotIn("freeform_place_resolution", provider.structured_calls)
                self.assertNotIn("destination_resolution", provider.structured_calls)

    def test_the_faroe_islands_by_their_own_name_are_still_the_faroe_islands(self):
        _, _, card = self.card_for("Faroe Islands", "Faroe Islands")

        self.assert_search_for(card, "Faroe Islands", "Faroe Islands", catalog_slug="ilhas-faroe")

    def test_a_name_that_only_starts_a_longer_catalog_name_is_not_that_place(self):
        make_destination(
            "porto-seguro-br", name="Porto Seguro", country="Brazil", trip_type="beach"
        )
        Destination.objects.filter(slug="porto-pt").delete()
        provider, shown, card = self.card_for(
            "Porto", "Portugal", freeform_place=real_place("Porto", "Portugal")
        )

        self.assert_search_for(card, "Porto", "Portugal")
        self.assertEqual(shown.recommendations, [])

    def test_a_misspelled_or_translated_name_reaches_its_catalog_place_through_the_standard_name(
        self,
    ):
        provider, shown, card = self.card_for(
            "Xangai", "China", freeform_place=real_place("Shanghai", "China")
        )

        self.assert_search_for(card, "Shanghai", "China", catalog_slug="xangai-cn")
        self.assertNotIn("destination_resolution", provider.structured_calls)

    def test_the_standard_name_does_not_cross_into_another_country(self):
        make_destination("valencia-ve", name="Valencia", country="Venezuela", trip_type="city")

        _, shown, card = self.card_for(
            "Valencia", "Spain", freeform_place=real_place("Valencia", "Spain")
        )

        self.assert_search_for(card, "Valencia", "Spain")
        self.assertEqual(shown.recommendations, [])

    def test_a_catalog_match_in_another_country_than_the_message_implies_is_dropped(self):
        make_destination("valencia-ve", name="Valencia", country="Venezuela", trip_type="city")

        # The message implies Spain; the one catalog "Valencia" is Venezuelan.
        _, shown, card = self.card_for(
            "Valencia",
            "Spain",
            freeform_place=real_place("Valencia", "Spain"),
            destination_resolution={"slug": "valencia-ve"},
        )

        self.assertTrue(card["freeform"])
        self.assertEqual(self.search_term(card), "Valencia, Spain")

    def test_two_places_with_one_name_go_by_the_country_the_message_implies(self):
        make_destination("granada-es", name="Granada", country="Spain", trip_type="culture")
        make_destination("granada-ni", name="Granada", country="Nicaragua", trip_type="city")

        for country, slug in (("Nicaragua", "granada-ni"), ("Spain", "granada-es")):
            with self.subTest(country=country):
                provider = ScriptedProvider(
                    [
                        turn(
                            {
                                "country": country,
                                "continent": "europe",
                                "is_accommodation_request": True,
                                "accommodation_place_name": "Granada",
                            },
                            trip_details={**WHEN, "adults": 2},
                        )
                    ]
                )
                shown = self.tab(provider).post("hospedagem em Granada, dia 5, 3 dias, somos 2")

                (card,) = shown.cards
                self.assertEqual(card["slug"], slug)
                self.assertNotIn("freeform_place_resolution", provider.structured_calls)

    def test_a_name_that_is_not_a_real_place_is_still_not_searched(self):
        provider = ScriptedProvider(
            [
                turn(
                    portugal(is_accommodation_request=True, accommodation_place_name="Narnia"),
                    trip_details={**WHEN, "adults": 2},
                    destination_resolution={"slug": "porto-pt"},
                    freeform_place={"is_real_place": False, "name": None, "country": None},
                )
            ]
        )

        shown = self.tab(provider).post("hospedagem em Narnia, dia 5, 3 dias, somos 2")

        self.assertEqual(shown.cards, [])
        self.assertEqual(shown.recommendations, [])
        self.assertIn("isn't in our curated catalog", self.prompt_of_last_reply(provider))
        self.assertNotIn("destination_resolution", provider.structured_calls)


# --- 2. a request to book, a request to open the search again ---------------------------------


class BookingRequestTests(_PortugalCase):
    def booking_for(self, place, **extra):
        return turn(
            portugal(
                is_booking_request=True,
                is_accommodation_request=True,
                accommodation_place_name=place,
            ),
            trip_details={**WHEN, "adults": 2},
            destination_resolution=NEAREST.get(place, {}),
            freeform_place=real_place(place, "Portugal"),
            **extra,
        )

    def test_a_booking_request_searches_the_place_named_not_a_nearby_one(self):
        for place in ("Coimbra", "Faro"):
            with self.subTest(place=place):
                provider = ScriptedProvider([self.booking_for(place)])

                shown = self.tab(provider).post(
                    f"Quero reservar um hotel em {place} de 5 a 8 de dezembro para 2 adultos"
                )

                (card,) = shown.cards
                self.assert_search_for(card, place, "Portugal")
                self.assertNotIn("destination_resolution", provider.structured_calls)
                self.assertIn("They used booking wording", self.prompt_of_last_reply(provider))

    def test_it_is_not_the_destination_chosen_earlier_either(self):
        provider = ScriptedProvider(
            [turn(portugal(selected_destination_name="Lisbon")), self.booking_for("Faro")]
        )
        tab = self.tab(provider)
        tab.post("quero ir pra Lisboa")

        shown = tab.post("quero reservar um hotel em Faro, dia 5, 3 dias, somos 2")

        (card,) = shown.cards
        self.assert_search_for(card, "Faro", "Portugal")
        # Naming a place to search stays chooses nothing: the choice made earlier stands.
        self.assertEqual(
            self.selected(), {"slug": "lisboa-pt", "name": "Lisbon", "country": "Portugal"}
        )

    def test_asking_to_open_the_search_again_opens_the_place_that_was_chosen(self):
        first = turn(
            portugal(
                is_accommodation_request=True,
                accommodation_place_name="Coimbra",
                selected_destination_name="Coimbra",
            ),
            trip_details={**WHEN, "adults": 2},
            destination_resolution=NEAREST["Coimbra"],
            freeform_place=real_place("Coimbra", "Portugal"),
        )
        provider = ScriptedProvider([first, turn(portugal())])
        tab = self.tab(provider)
        tab.post("Coimbra, dia 5, 3 dias, somos 2")

        again = tab.post("abre a busca de novo")

        (card,) = again.cards
        self.assert_search_for(card, "Coimbra", "Portugal")
        self.assertNotIn("destination_resolution", provider.structured_calls)


# --- 3. a visit reported, a trip for someday ----------------------------------------------------


class FeedbackTests(_PortugalCase):
    def feedback_about(self, place, *, country, rating=9, **script):
        return ScriptedProvider(
            [
                turn(
                    {
                        "message_type": "feedback",
                        "feedback_destination_name": place,
                        "feedback_rating": rating,
                    },
                    destination_resolution=NEAREST.get(place, {}),
                    freeform_place=real_place(place, country),
                    **script,
                )
            ]
        )

    def test_feedback_about_faro_is_not_stored_against_the_faroe_islands(self):
        provider = self.feedback_about("Faro", country="Portugal")

        result, _, _ = self.say(provider, "Já fui a Faro e adorei, dou nota 9")

        self.assertEqual(TravelHistoryEntry.objects.count(), 0)
        self.assertEqual(Feedback.objects.count(), 0)
        self.assertEqual(result.recommendations, [])
        self.assertNotIn("destination_resolution", provider.structured_calls)
        # The reply is the general-knowledge one, about the place they named.
        self.assertIn("Faro", self.prompt_of_last_reply(provider))

    def test_feedback_about_coimbra_is_not_stored_against_porto(self):
        provider = self.feedback_about("Coimbra", country="Portugal", rating=8)

        self.say(provider, "Já estive em Coimbra, foi uma experiência 8 de 10")

        self.assertEqual(TravelHistoryEntry.objects.count(), 0)
        self.assertEqual(Feedback.objects.count(), 0)

    def test_feedback_about_a_catalog_place_is_still_registered(self):
        provider = self.feedback_about("Faroe Islands", country="Faroe Islands", rating=9)

        self.say(provider, "Já fui às Ilhas Faroe e adorei, dou nota 9")

        (visit,) = TravelHistoryEntry.objects.all()
        self.assertEqual(visit.destination.slug, "ilhas-faroe")
        (feedback,) = Feedback.objects.all()
        self.assertEqual((feedback.destination.slug, feedback.rating), ("ilhas-faroe", 9))
        # A catalog place named exactly costs no model call beyond the intent's.
        self.assertNotIn("freeform_place_resolution", provider.structured_calls)

    def test_feedback_in_another_language_reaches_the_catalog_place_through_its_standard_name(self):
        provider = ScriptedProvider(
            [
                turn(
                    {
                        "message_type": "feedback",
                        "feedback_destination_name": "Lisboa",
                        "feedback_rating": 10,
                    },
                    destination_resolution={"slug": "porto-pt"},
                    freeform_place=real_place("Lisbon", "Portugal"),
                )
            ]
        )

        self.say(provider, "Adorei Lisboa, nota 10")

        (visit,) = TravelHistoryEntry.objects.all()
        self.assertEqual(visit.destination.slug, "lisboa-pt")

    def test_a_country_is_not_a_destination_and_nothing_is_registered_against_a_city_of_it(self):
        provider = self.feedback_about("Portugal", country="Portugal")

        self.say(provider, "Já fui a Portugal e adorei, dou nota 9")

        self.assertEqual(TravelHistoryEntry.objects.count(), 0)
        self.assertEqual(Feedback.objects.count(), 0)


class FutureTripTests(_PortugalCase):
    def wish_for(self, place, *, country):
        return ScriptedProvider(
            [
                turn(
                    {"message_type": "future_intent", "future_destination_name": place},
                    destination_resolution=NEAREST.get(place, {}),
                    freeform_place=real_place(place, country),
                )
            ]
        )

    def test_a_future_trip_to_coimbra_does_not_create_a_porto_trip(self):
        provider = self.wish_for("Coimbra", country="Portugal")

        result, _, _ = self.say(provider, "Um dia quero ir a Coimbra")

        self.assertEqual(Trip.objects.count(), 0)
        self.assertEqual(result.recommendations, [])
        self.assertNotIn("destination_resolution", provider.structured_calls)
        self.assertIn("Coimbra", self.prompt_of_last_reply(provider))

    def test_a_future_trip_to_faro_does_not_create_a_faroe_islands_trip(self):
        provider = self.wish_for("Faro", country="Portugal")

        self.say(provider, "Um dia quero ir a Faro")

        self.assertEqual(Trip.objects.count(), 0)

    def test_a_future_trip_to_a_catalog_place_is_still_saved(self):
        provider = self.wish_for("Porto", country="Portugal")

        self.say(provider, "Um dia quero ir ao Porto")

        (trip,) = Trip.objects.all()
        self.assertEqual((trip.destination.slug, trip.name), ("porto-pt", "Someday: Porto"))
        self.assertNotIn("freeform_place_resolution", provider.structured_calls)

    def test_a_future_trip_under_another_languages_name_is_saved_for_the_catalog_place(self):
        provider = ScriptedProvider(
            [
                turn(
                    {"message_type": "future_intent", "future_destination_name": "Xangai"},
                    destination_resolution={"slug": "porto-pt"},
                    freeform_place=real_place("Shanghai", "China"),
                )
            ]
        )

        self.say(provider, "Um dia quero conhecer Xangai")

        (trip,) = Trip.objects.all()
        self.assertEqual(trip.destination.slug, "xangai-cn")


# --- 4. the lookup itself ------------------------------------------------------------------------


class _OneAnswer:
    """Answers every structured call with one scripted dict and remembers which were asked."""

    def __init__(self, answer):
        self.answer = answer
        self.asked = []

    def generate_structured_reply(
        self, messages, *, json_schema, max_tokens=None, temperature=None
    ):
        self.asked.append(json_schema["name"])
        return dict(self.answer)


class NamedPlaceTests(TestCase):
    def setUp(self):
        make_destination("porto-pt", name="Porto", country="Portugal", trip_type="city")
        make_destination(
            "ilhas-faroe", name="Faroe Islands", country="Faroe Islands", trip_type="nature"
        )

    def test_a_catalog_place_comes_back_with_its_row_and_no_model_call(self):
        provider = _OneAnswer({})

        record, destination = _named_place(
            "porto", country_hint="Portugal", ai_provider=provider
        )

        self.assertEqual(record, {"slug": "porto-pt", "name": "Porto", "country": "Portugal"})
        self.assertEqual(destination.slug, "porto-pt")
        self.assertEqual(provider.asked, [])

    def test_a_real_place_outside_the_catalog_comes_back_as_itself_with_no_row(self):
        provider = _OneAnswer(real_place("Faro", "Portugal"))

        record, destination = _named_place("Faro", country_hint="Portugal", ai_provider=provider)

        self.assertEqual(record, {"slug": None, "name": "Faro", "country": "Portugal"})
        self.assertIsNone(destination)
        self.assertEqual(provider.asked, ["freeform_place_resolution"])

    def test_the_faroe_islands_are_not_found_by_the_start_of_their_name(self):
        provider = _OneAnswer({"is_real_place": False, "name": None, "country": None})

        self.assertIsNone(_named_place("Faro", country_hint=None, ai_provider=provider))

    def test_nothing_named_is_nothing(self):
        provider = _OneAnswer({})

        self.assertIsNone(_named_place(None, country_hint=None, ai_provider=provider))
        self.assertIsNone(_named_place("", country_hint=None, ai_provider=provider))
        self.assertEqual(provider.asked, [])

    def test_a_catalog_record_whose_row_is_gone_is_no_place(self):
        # A record that names a catalog slug the table no longer has cannot be searched,
        # saved or registered as that place: it is dropped rather than half-used.
        gone = {"slug": "gone-pt", "name": "Gone", "country": "Portugal"}

        with mock.patch("ai.orchestration._resolve_selected_destination", return_value=gone):
            self.assertIsNone(
                _named_place("Gone", country_hint=None, ai_provider=_OneAnswer({}))
            )
