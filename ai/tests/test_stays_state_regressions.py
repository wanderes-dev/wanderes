"""Whole-turn regressions for how the stays action and the trip state hold up
across a conversation: the place chosen in a stays request is kept, a date is
not swallowed by a recall label, a short answer is read as the answer it is, and
the question about the profile's party is read against what was asked."""

from ai.orchestration import _drop_ungrounded_selection, _drop_unoffered_bare_selection
from ai.tests.helpers import ScriptedProvider
from ai.tests.test_selected_destination import WHEN, barcelona_record, spain, turn
from ai.tests.test_trip_details_flow import _TripCase, plain, stays
from users.models import TravelerProfile


class StaysTurnKeepsTheChoiceTests(_TripCase):
    """A message that both chooses a place and asks for its stays ("Quero ir pra
    Barcelona dia 5, 3 dias, somos 2") records the choice, so the next message is
    about that place and not a fresh choice of it - with its description and a
    second Booking button."""

    def chooses_and_asks_for_stays(self, place="Barcelona"):
        return turn(
            spain(
                is_accommodation_request=True,
                accommodation_place_name=place,
                selected_destination_name=place,
            ),
            trip_details={**WHEN, "adults": 2},
        )

    def test_the_place_chosen_in_a_stays_request_is_kept(self):
        provider = ScriptedProvider([self.chooses_and_asks_for_stays()])

        self.say(provider, "quero ir pra Barcelona dia 5, 3 dias, somos 2")

        self.assertEqual(self.selected(), barcelona_record())

    def test_the_next_question_is_carried_not_a_fresh_choice(self):
        provider = ScriptedProvider(
            [
                self.chooses_and_asks_for_stays(),
                turn(spain(selected_destination_name="Barcelona")),
            ]
        )
        self.say(provider, "quero ir pra Barcelona dia 5, 3 dias, somos 2")

        result, _, _ = self.say(provider, "tem alguma dica de transporte por lá?")

        self.assert_carried_on(result, provider, "Barcelona, Spain")

    def test_a_booking_request_that_chooses_the_place_keeps_it_too(self):
        provider = ScriptedProvider(
            [
                turn(
                    spain(
                        is_booking_request=True,
                        is_accommodation_request=True,
                        accommodation_place_name="Barcelona",
                        selected_destination_name="Barcelona",
                    ),
                    trip_details={**WHEN, "adults": 2},
                )
            ]
        )

        self.say(provider, "reserva Barcelona dia 5, 3 dias, somos 2")

        self.assertEqual(self.selected(), barcelona_record())

    def test_a_place_outside_the_catalog_is_kept_under_its_own_name(self):
        provider = ScriptedProvider(
            [
                turn(
                    spain(
                        is_accommodation_request=True,
                        accommodation_place_name="Valencia",
                        selected_destination_name="Valencia",
                    ),
                    freeform_place={"is_real_place": True, "name": "Valencia", "country": "Spain"},
                    trip_details={**WHEN, "adults": 2},
                )
            ]
        )

        self.say(provider, "quero ir pra Valência dia 5, 3 dias, somos 2")

        self.assertEqual(self.selected(), {"slug": None, "name": "Valencia", "country": "Spain"})

    def test_a_stays_request_that_only_names_a_place_chooses_nothing(self):
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

        self.say(provider, "e hospedagem em Madrid? somos 2, dia 5, 3 dias")

        self.assertEqual(self.selected(), barcelona_record())

    def test_a_closest_match_for_the_stays_lookup_is_not_taken_as_the_choice(self):
        # Valencia is not in the catalog; the closest-match step answers Madrid.
        provider = ScriptedProvider(
            [
                turn(
                    spain(
                        is_accommodation_request=True,
                        accommodation_place_name="Valencia",
                        selected_destination_name="Valencia",
                    ),
                    destination_resolution={"slug": "madrid-es"},
                    trip_details={**WHEN, "adults": 2},
                )
            ]
        )

        self.say(provider, "quero ir pra Valência dia 5, 3 dias, somos 2")

        self.assertIsNone(self.selected())


class RecallLabelDoesNotSwallowADetailTests(_TripCase):
    """A message like "volta pra dia 12 de dezembro" is a date for the trip,
    whatever the model made of the word "volta"."""

    READY = turn(
        spain(
            is_accommodation_request=True,
            accommodation_place_name="Barcelona",
            selected_destination_name="Barcelona",
        ),
        trip_details={**WHEN, "adults": 2},
    )

    def test_a_date_that_reads_like_a_recall_is_applied_not_recalled(self):
        provider = ScriptedProvider(
            [
                self.READY,
                turn(
                    spain(
                        is_recall_request=True,
                        is_accommodation_request=True,
                        accommodation_place_name="Barcelona",
                    ),
                    trip_details={"start": {"day": 12, "month": 12}},
                ),
            ]
        )
        self.say(provider, "quero ir pra Barcelona dia 5, 3 dias, somos 2")

        result, _, _ = self.say(provider, "volta pra dia 12 de dezembro")

        self.assertEqual(self.stored()["start_date"], "2026-12-12")
        self.assertNotIn("recall or repeat", self.prompt_of_last_reply(provider))
        self.assertTrue(result.retire_stays)
        self.assertTrue(self.has_search(result))

    def test_a_real_recall_is_still_a_recall_and_reads_nothing(self):
        provider = ScriptedProvider([self.READY, turn(spain(is_recall_request=True))])
        self.say(provider, "quero ir pra Barcelona dia 5, 3 dias, somos 2")
        before = self.stored()

        self.say(provider, "voltando, quais eram mesmo?")

        self.assertIn("recall or repeat", self.prompt_of_last_reply(provider))
        self.assertEqual(self.stored(), before)


class ShortReplyGateTests(_TripCase):
    """A trip with its dates and nobody going is waiting for one answer; a short
    reply with no cue word in it ("sou só eu") is read as that answer - but only
    right after a question."""

    ASKED = "How many people are going?"

    def dated(self, reply_text, *later):
        provider = ScriptedProvider([stays(**WHEN), *later], reply_text=reply_text)
        self.say(provider, "hospedagem em Barcelona dia 5, 3 dias")
        return provider

    def test_a_short_answer_after_the_question_is_read(self):
        provider = self.dated(self.ASKED, plain(adults=1))

        self.say(provider, "sou só eu")

        self.assertEqual(self.stored()["adults"], 1)
        self.assertEqual(self.trip_calls(provider), 2)

    def test_the_same_words_after_no_question_are_not_read(self):
        provider = self.dated("Here is what I found.", plain(adults=1))

        self.say(provider, "sou só eu")

        self.assertIsNone(self.stored()["adults"])
        self.assertEqual(self.trip_calls(provider), 1)

    def test_a_long_message_is_left_to_the_cue_words(self):
        provider = self.dated(self.ASKED, plain(adults=1))

        self.say(provider, "bom, vou pensar com calma e eu volto aqui para falar com voce")

        self.assertEqual(self.trip_calls(provider), 1)

    def test_a_statement_filed_as_an_activity_question_is_still_read(self):
        provider = self.dated(
            self.ASKED, turn(spain(is_activity_question=True), trip_details={"adults": 2})
        )

        self.say(provider, "somos 2")

        self.assertEqual(self.stored()["adults"], 2)

    def test_a_real_activity_question_reads_nothing(self):
        provider = self.dated(
            self.ASKED, turn(spain(is_activity_question=True), trip_details={"stay_length": 9})
        )

        self.say(provider, "o que fazer em 3 dias?")

        self.assertEqual(self.stored()["stay_length"], 3)
        self.assertEqual(self.trip_calls(provider), 1)


class UngroundedSelectionTests(_TripCase):
    """A message that doesn't name a place or point at an option picks none:
    "alguma dessas serve pra criança?" or "no beaches please" is not "I'll take
    the first one"."""

    def test_a_message_that_names_no_place_drops_the_selection(self):
        for message in (
            "alguma dessas serve pra criança pequena?",
            "e qual delas é a mais barata?",
            "¿cuál es más económico?",
            "which of those is better for kids?",
            "no beaches please",
            "somewhere not too crowded",
            "algo en América Latina mejor",
        ):
            with self.subTest(message=message):
                fields = spain(selected_destination_name="Barcelona")

                _drop_ungrounded_selection(message, fields)

                self.assertIsNone(fields["selected_destination_name"])

    def test_pointing_at_an_option_or_accepting_one_keeps_the_selection(self):
        for message in (
            "a primeira",
            "esse mesmo",
            "sim",
            "yes, please",
            "la 2",
            "the second",
            "pode ser",
            "sounds good",
        ):
            with self.subTest(message=message):
                fields = spain(selected_destination_name="Barcelona")

                _drop_ungrounded_selection(message, fields)

                self.assertEqual(fields["selected_destination_name"], "Barcelona")

    def test_a_change_of_mind_word_makes_a_name_a_statement(self):
        intent = {"selected_destination_name": "Seville"}

        _drop_unoffered_bare_selection(
            "mejor Sevilla", intent, [{"role": "assistant", "content": "Madrid es genial."}]
        )

        self.assertEqual(intent["selected_destination_name"], "Seville")

    def test_a_question_that_names_the_place_keeps_it_however_it_is_spelled(self):
        for message, name in (
            ("Barcelona é seguro pra crianças?", "Barcelona"),
            ("e Lisboa, vale a pena?", "Lisbon"),
            ("¿Sevilla tiene buen clima en mayo?", "Seville"),
            ("is Rio safe?", "Rio de Janeiro"),
        ):
            with self.subTest(message=message):
                fields = spain(selected_destination_name=name)

                _drop_ungrounded_selection(message, fields)

                self.assertEqual(fields["selected_destination_name"], name)

    def test_a_question_with_a_choice_word_in_it_keeps_the_selection(self):
        fields = spain(selected_destination_name="Barcelona")

        _drop_ungrounded_selection("qual é mais barata? vou na primeira", fields)

        self.assertEqual(fields["selected_destination_name"], "Barcelona")

    def test_a_statement_is_never_touched(self):
        fields = spain(selected_destination_name="Barcelona")

        _drop_ungrounded_selection("a primeira, por favor", fields)

        self.assertEqual(fields["selected_destination_name"], "Barcelona")

    def test_asking_about_the_options_does_not_lock_the_conversation_on_the_first_one(self):
        provider = ScriptedProvider(
            [turn(spain()), turn(spain(selected_destination_name="Barcelona"))]
        )
        self.say(provider, "quero uma cidade na Espanha")

        result, _, _ = self.say(provider, "alguma dessas serve pra criança pequena?")

        self.assertIsNone(self.selected())
        self.assertFalse(result.is_destination_detail)


class PendingPartyQuestionContextTests(_TripCase):
    """While the question about the profile's party is pending, the model that
    reads the "sim" is told what was asked - not shown the reply, whose wording
    ("com mais duas pessoas") it could read a head count from."""

    def test_the_extraction_sees_what_was_asked_not_the_reply(self):
        TravelerProfile.objects.create(user=self.user, travelers_count=2)
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona"), trip_details=WHEN),
                plain(confirms_party_offer=True),
            ],
            reply_text="Você vai viajar com mais duas pessoas, todas adultas?",
        )
        self.say(provider, "quero ir pra Barcelona dia 5, 3 dias")

        self.say(provider, "sim")

        shown = provider.trip_details_messages[-1][-1].content
        self.assertIn("are all adults", shown)
        self.assertNotIn("duas", shown)
        self.assertEqual(self.stored()["adults"], 2)


class StartOverTests(_TripCase):
    """A message like "forget everything, let's start over" drops the trip, the
    place and the buttons - what was forgotten must not come back in the next
    search."""

    READY = turn(
        spain(
            is_accommodation_request=True,
            accommodation_place_name="Barcelona",
            selected_destination_name="Barcelona",
        ),
        trip_details={**WHEN, "adults": 2},
    )

    def test_forgetting_everything_drops_the_trip_the_place_and_the_buttons(self):
        provider = ScriptedProvider(
            [self.READY, turn({}, trip_details={"cleared_fields": ["everything"]})]
        )
        self.say(provider, "quero ir pra Barcelona dia 5, 3 dias, somos 2")
        self.assertEqual(self.selected(), barcelona_record())

        result, _, _ = self.say(provider, "esquece tudo, vamos recomeçar do zero")

        self.assertIsNone(self.stored())
        self.assertIsNone(self.selected())
        self.assertTrue(result.retire_stays)

    def test_the_next_search_starts_from_nothing(self):
        provider = ScriptedProvider(
            [
                self.READY,
                turn({}, trip_details={"cleared_fields": ["everything"]}),
                turn(spain(selected_destination_name="Madrid")),
            ]
        )
        self.say(provider, "quero ir pra Barcelona dia 5, 3 dias, somos 2")
        self.say(provider, "esquece tudo, vamos recomeçar do zero")

        result, _, _ = self.say(provider, "quero ir pra Madrid")

        self.assert_detail_of(result, "madrid-es")
        self.assertFalse(self.has_search(result))
        self.assertIsNone(self.stored())
        self.assertIn("Dates: none set", self.prompt_of_last_reply(provider))

    def test_a_clear_of_everything_needs_a_message_that_actually_starts_over(self):
        provider = ScriptedProvider(
            [self.READY, turn({}, trip_details={"cleared_fields": ["everything"]})]
        )
        self.say(provider, "quero ir pra Barcelona dia 5, 3 dias, somos 2")

        self.say(provider, "essa data está errada, esquece isso")

        self.assertEqual(self.stored()["adults"], 2)
        self.assertEqual(self.selected(), barcelona_record())


class ShowTheStaysAgainTests(_TripCase):
    """A message like "me mostra de novo as hospedagens" gets the search back - it
    is not a request to recall what was said."""

    def test_the_search_comes_back_instead_of_a_retelling(self):
        ready = turn(
            spain(
                is_accommodation_request=True,
                accommodation_place_name="Barcelona",
                selected_destination_name="Barcelona",
            ),
            trip_details={**WHEN, "adults": 2},
        )
        again = turn(
            spain(
                is_recall_request=True,
                is_accommodation_request=True,
                accommodation_place_name="Barcelona",
                selected_destination_name="Barcelona",
            )
        )
        provider = ScriptedProvider([ready, again])
        self.say(provider, "quero ir pra Barcelona dia 5, 3 dias, somos 2")

        result, _, _ = self.say(provider, "me mostra de novo as hospedagens")

        self.assertTrue(self.has_search(result))
        self.assertNotIn("recall or repeat", self.prompt_of_last_reply(provider))


class LocalizedPlaceNameTests(_TripCase):
    """A place called "Sevilla" is Seville: a stays request that chooses a place
    under another language's name keeps the catalog place as the choice."""

    def test_the_choice_is_kept_under_the_catalog_name(self):
        provider = ScriptedProvider(
            [
                turn(
                    spain(
                        is_accommodation_request=True,
                        accommodation_place_name="Sevilla",
                        selected_destination_name="Sevilla",
                    ),
                    destination_resolution={"slug": "sevilha-es"},
                    freeform_place={"is_real_place": True, "name": "Seville", "country": "Spain"},
                    trip_details={**WHEN, "adults": 2},
                )
            ]
        )

        self.say(provider, "Quiero ir a Sevilla el 5, 3 noches, somos 2")

        self.assertEqual(
            self.selected(), {"slug": "sevilha-es", "name": "Seville", "country": "Spain"}
        )
