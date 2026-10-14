"""The person who joined and has no age yet, settled by what the traveler says about them next.

A cousin or a sister who joins with no age is held as one more child with no age: the search
waits and the reply asks how old they are. The traveler may answer with something other than an
age - "he's an adult", "he can't come", "just the two of us". Those are read from the words, not
by the model: asked about "he's an adult" it answers a head count of one, which used to replace
the two confirmed adults, and "he can't come" has no cue word that opens the extraction at all.

What the words settle is exactly one person. An adult joins the adults; a person who is not
coming is dropped; anything the code cannot settle without guessing (several people waiting, a
different head count, a plural, a bare "an adult") is a question and changes nothing. The
confirmed party is never replaced."""

from django.test import SimpleTestCase

from ai.tests.helpers import ScriptedProvider
from ai.tests.test_party_updates import hear, issues_of, link_of, party, who
from ai.tests.test_selected_destination import WHEN, spain, turn
from ai.tests.test_trip_details import TODAY, comps
from ai.tests.test_trip_details_flow import _TripCase, query_of, stays
from ai.trip_details import (
    TripTurn,
    apply_components,
    fact_block,
    pending_person_statement,
    resolve,
)
from evaluations.view_path import ViewSession

# Two confirmed adults and a cousin whose age nobody has said.
WAITING = party(2, 1)

ADULT_CONFIRMATIONS = [
    ("en", "he's an adult"),
    ("en", "She is a grown-up"),
    ("en", "yes, he's an adult"),
    ("en", "my cousin is an adult"),
    ("pt-br", "ele é adulto"),
    ("pt-br", "ela é adulta"),
    ("pt-br", "meu primo é adulto"),
    ("pt-br", "sim, ele é adulto"),
    ("pt-br", "ele é maior de idade"),
    ("pt-pt", "ele já é adulto"),
    ("pt-pt", "o meu irmão é adulto"),
    ("es", "él es adulto"),
    ("es", "ella es adulta"),
    ("es", "mi hermano es adulto"),
    ("es", "es mayor de edad"),
]

CANCELLATIONS = [
    ("en", "he can't come"),
    ("en", "actually he can't come after all"),
    ("en", "she won't be coming"),
    ("en", "my brother isn't coming"),
    ("en", "he dropped out"),
    ("pt-br", "ele não vai mais"),
    ("pt-br", "na verdade ele não vai mais"),
    ("pt-br", "ela não pode ir"),
    ("pt-br", "ele desistiu"),
    ("pt-pt", "o meu primo já não vem"),
    ("pt-pt", "ele já não vai"),
    ("es", "ya no viene"),
    ("es", "él no viene"),
    ("es", "mi hermano desistió"),
]

# The party restated as the people already counted.
JUST_US = [
    ("en", "just the two of us"),
    ("en", "we are just the two of us then"),
    ("en", "only us"),
    ("pt-br", "só nós dois"),
    ("pt-br", "somos só nós dois"),
    ("pt-pt", "somos apenas 2"),
    ("es", "solo nosotros dos"),
    ("es", "somos solo dos"),
]

# What the live extraction returned for these messages, and what it could return: a head count of
# one, a restated head count, no children, someone joining - or nothing.
MODEL_SHAPES = [
    ("nothing returned", {}),
    ("one adult, the live answer to 'an adult'", dict(adults=1)),
    ("the confirmed head count restated", dict(adults=2)),
    ("no children", dict(children=0)),
    ("an adult joining", dict(added=[("adult", None)])),
]


# --- 1. what the words say -------------------------------------------------------------------


class StatementTests(SimpleTestCase):
    def test_an_adult_confirmation_is_read_as_one(self):
        for language, message in ADULT_CONFIRMATIONS:
            with self.subTest(language=language, message=message):
                self.assertEqual(pending_person_statement(message, WAITING), "adult")

    def test_a_cancellation_is_read_as_one(self):
        for language, message in [*CANCELLATIONS, *JUST_US]:
            with self.subTest(language=language, message=message):
                self.assertEqual(pending_person_statement(message, WAITING), "not_coming")

    def test_nothing_is_settled_when_nobody_is_waiting(self):
        for language, message in [*ADULT_CONFIRMATIONS, *CANCELLATIONS, *JUST_US]:
            with self.subTest(language=language, message=message):
                self.assertIsNone(pending_person_statement(message, party(2)))
                self.assertIsNone(pending_person_statement(message, party(2, 1, [6])))

    def test_a_message_about_anything_else_settles_nothing(self):
        for message in (
            "o hotel não vai mais ter vaga",
            "I can't come",
            "nós não vamos mais",
            "we can't come",
            "he can't come on the 5th",
            "ele não vai dia 5",
            "is he an adult?",
            "ele é adulto?",
            "ele é adulto e vamos dia 5",
            "he's an adult and we leave on the 5th",
            "ele tem 25 anos",
            "he's 30",
            "somos 3 adultos",
            "2 adults",
            "quero um hotel para adultos",
            "ele não gosta de praia",
            "e meu primo vai também",
            "my brother is coming too",
            "ok",
            "obrigado",
        ):
            with self.subTest(message=message):
                self.assertIsNone(pending_person_statement(message, WAITING))

    def test_and_an_adult_is_not_he_is_an_adult(self):
        # Without accents the Portuguese "é" and "e" are one letter.
        for message in ("e um adulto", "e uma adulta", "sim, e um adulto"):
            with self.subTest(message=message):
                self.assertIsNone(pending_person_statement(message, WAITING))
        self.assertEqual(pending_person_statement("é adulto", WAITING), "adult")
        self.assertEqual(pending_person_statement("ele é um adulto", WAITING), "adult")
        self.assertEqual(pending_person_statement("es un adulto", WAITING), "adult")

    def test_not_being_an_adult_settles_nothing_the_age_is_still_needed(self):
        for message in ("he's not an adult", "ele não é adulto", "ella no es adulta"):
            with self.subTest(message=message):
                self.assertIsNone(pending_person_statement(message, WAITING))

    def test_an_answer_that_could_mean_several_things_is_a_question(self):
        for message in (
            "they're adults",
            "são adultos",
            "ambos são adultos",
            "an adult",
            "um adulto",
            "adultos",
            "they can't come",
            "eles não vão mais",
            "nobody else is coming",
            "ninguém mais vai",
            "nadie más viene",
        ):
            with self.subTest(message=message):
                self.assertEqual(pending_person_statement(message, WAITING), "unclear")

    def test_with_several_people_waiting_which_one_is_meant_is_a_question(self):
        two_waiting = party(2, 2)
        for message in ("he's an adult", "ele é adulto", "he can't come", "só nós dois"):
            with self.subTest(message=message):
                self.assertEqual(pending_person_statement(message, two_waiting), "unclear")

    def test_a_head_count_that_is_not_the_people_already_counted_is_a_question(self):
        self.assertEqual(pending_person_statement("just the two of us", party(3, 1)), "unclear")
        self.assertEqual(pending_person_statement("only the three of us", WAITING), "unclear")
        # Two adults and a child of 6 are the three of them.
        self.assertEqual(
            pending_person_statement("only the three of us", party(2, 2, [6])), "not_coming"
        )

    def test_with_no_adults_on_record_an_adult_has_nothing_to_join(self):
        self.assertEqual(pending_person_statement("he's an adult", party(None, 1)), "unclear")


# --- 2. he is an adult ---------------------------------------------------------------------------


class AdultConfirmationTests(SimpleTestCase):
    def test_the_person_becomes_one_more_adult_whatever_the_model_answered(self):
        for language, message in ADULT_CONFIRMATIONS:
            for label, model in MODEL_SHAPES:
                with self.subTest(language=language, message=message, model=label):
                    applied = hear(message, WAITING, **model)

                    self.assertEqual(who(applied), (3, 0, None))
                    self.assertEqual(issues_of(applied), [])
                    self.assertEqual(applied.pending_resolved, "adult")
                    self.assertFalse(applied.ask_child_ages)

    def test_the_confirmed_adults_are_never_replaced_by_the_one_adult_in_the_words(self):
        for adults in (2, 3, 4):
            with self.subTest(adults=adults):
                applied = hear("he's an adult", party(adults, 1), adults=1)

                self.assertEqual(who(applied), (adults + 1, 0, None))

    def test_the_search_is_ready_with_the_new_party(self):
        before = resolve(WAITING, TODAY)
        applied = hear("ele é adulto", WAITING, adults=1)
        after = resolve(applied.record, TODAY)

        self.assertIsNone(before.search_kwargs())
        self.assertEqual(after.missing_for_search, ())
        self.assertEqual(link_of(applied)["adults"], 3)
        self.assertNotIn("children", link_of(applied))
        self.assertTrue(applied.details_changed)

    def test_the_children_whose_ages_are_known_stay_as_they_are(self):
        applied = hear("ele é adulto", party(2, 2, [6]), adults=1)

        self.assertEqual(who(applied), (3, 1, [6]))
        self.assertEqual(resolve(applied.record, TODAY).missing_for_search, ())

    def test_it_is_settled_once_when_the_turn_runs_twice(self):
        first = hear("he's an adult", WAITING, turn_key=11, adults=1)
        again = hear("he's an adult", first.record, turn_key=11, adults=1)
        later = hear("he's an adult", first.record, turn_key=12, adults=1)

        self.assertEqual(who(first), (3, 0, None))
        self.assertEqual(who(again), (3, 0, None))
        self.assertIsNone(again.pending_resolved)
        # A statement about a grown-up is not a head count, with or without anyone waiting.
        self.assertEqual(who(later), (3, 0, None))
        self.assertFalse(later.changed)

    def test_nobody_waiting_means_the_statement_changes_nothing_and_is_no_head_count(self):
        applied = hear("he's an adult", party(2), adults=1)

        self.assertEqual(who(applied), (2, None, None))
        self.assertFalse(applied.changed)
        self.assertEqual(issues_of(applied), [])

    def test_with_two_waiting_nothing_changes_and_the_traveler_is_asked(self):
        applied = hear("he's an adult", party(2, 2), adults=1)

        self.assertEqual(who(applied), (2, 2, None))
        self.assertEqual(issues_of(applied), ["pending_person_unclear"])
        self.assertIsNone(applied.pending_resolved)

    def test_a_bare_adult_nothing_changes_and_the_traveler_is_asked(self):
        for message in ("um adulto", "an adult"):
            with self.subTest(message=message):
                applied = hear(message, WAITING, adults=1)

                self.assertEqual(who(applied), (2, 1, None))
                self.assertEqual(issues_of(applied), ["pending_person_unclear"])

    def test_not_being_an_adult_changes_nothing_and_is_no_head_count(self):
        applied = hear("ele não é adulto", WAITING, adults=1)

        self.assertEqual(who(applied), (2, 1, None))
        self.assertEqual(issues_of(applied), [])

    def test_an_age_still_decides_what_the_person_is(self):
        grown = hear("ele tem 25 anos", WAITING, ages=[25])
        young = hear("ele tem 12 anos", WAITING, ages=[12])

        self.assertEqual(who(grown), (3, 0, None))
        self.assertEqual(who(young), (2, 1, [12]))

    def test_a_party_that_would_be_too_large_is_a_question(self):
        applied = hear("he's an adult", party(30, 1), adults=1)

        self.assertEqual(who(applied), (30, 1, None))
        self.assertEqual(issues_of(applied), ["party_too_large"])


# --- 3. he is not coming -------------------------------------------------------------------------


class CancellationTests(SimpleTestCase):
    def test_the_person_is_dropped_and_the_confirmed_party_is_untouched(self):
        for language, message in [*CANCELLATIONS, *JUST_US]:
            for label, model in MODEL_SHAPES:
                with self.subTest(language=language, message=message, model=label):
                    applied = hear(message, WAITING, **model)

                    self.assertEqual(who(applied), (2, 0, None))
                    self.assertEqual(issues_of(applied), [])
                    self.assertEqual(applied.pending_resolved, "not_coming")
                    self.assertFalse(applied.ask_child_ages)  # nobody's age is asked for any more

    def test_the_search_comes_back_with_the_party_that_was_confirmed(self):
        applied = hear("ele não vai mais", WAITING)

        self.assertIsNone(resolve(WAITING, TODAY).search_kwargs())
        self.assertEqual(resolve(applied.record, TODAY).missing_for_search, ())
        self.assertEqual(link_of(applied)["adults"], 2)
        self.assertNotIn("children", link_of(applied))

    def test_the_other_children_on_record_keep_their_ages(self):
        for message in ("he can't come", "only the three of us"):
            with self.subTest(message=message):
                applied = hear(message, party(2, 2, [6]))

                self.assertEqual(who(applied), (2, 1, [6]))
                self.assertEqual(link_of(applied)["child_ages"], [6])

    def test_it_is_settled_once_when_the_turn_runs_twice(self):
        first = hear("he can't come", WAITING, turn_key=21)
        again = hear("he can't come", first.record, turn_key=21, adults=1)

        self.assertEqual(who(first), (2, 0, None))
        self.assertEqual(who(again), (2, 0, None))
        self.assertFalse(again.changed)

    def test_nobody_waiting_means_there_is_nothing_to_drop(self):
        for message in ("he can't come", "ele não vai mais"):
            with self.subTest(message=message):
                applied = hear(message, party(2, 1, [6]), adults=1)

                self.assertEqual(who(applied), (2, 1, [6]))
                self.assertFalse(applied.changed)

    def test_the_traveler_speaking_of_themselves_cancels_nobody(self):
        for message in ("I can't come", "nós não vamos mais", "he can't come on the 5th"):
            with self.subTest(message=message):
                applied = hear(message, WAITING)

                self.assertEqual(who(applied), (2, 1, None))
                self.assertIsNone(applied.pending_resolved)

    def test_with_two_waiting_or_a_plural_the_traveler_is_asked(self):
        for message, record in (
            ("he can't come", party(2, 2)),
            ("só nós dois", party(2, 2)),
            ("they can't come", WAITING),
            ("nobody else is coming", WAITING),
            ("ninguém mais vai", WAITING),
        ):
            with self.subTest(message=message):
                applied = hear(message, record, adults=1)

                self.assertEqual(who(applied), who(hear("ok", record)))
                self.assertEqual(issues_of(applied), ["pending_person_unclear"])

    def test_a_different_head_count_is_a_question_and_replaces_nobody(self):
        applied = hear("just the two of us", party(3, 1), adults=2)

        self.assertEqual(who(applied), (3, 1, None))
        self.assertEqual(issues_of(applied), ["pending_person_unclear"])

    def test_a_head_count_that_repeats_the_party_is_no_new_head_count(self):
        # "Just the two of us" for one adult and a child of 6 is the two already counted: the
        # model's "two adults" must not replace the one adult - with or without anyone waiting,
        # so a retry of the turn after the person was dropped cannot do it either.
        for record in (party(1, 1, [6]), party(2), party(2, 1, [6])):
            counted = (record["adults"] or 0) + len(record["child_ages"] or [])
            with self.subTest(record=who(hear("ok", record))):
                applied = hear(f"only the {counted} of us", record, adults=counted + 1)

                self.assertEqual(who(applied), who(hear("ok", record)))

    def test_a_head_count_that_is_new_still_replaces_the_party_when_nobody_waits(self):
        self.assertEqual(who(hear("just the two of us", party(1), adults=2)), (2, None, None))
        self.assertEqual(who(hear("just the two of us", party(3), adults=2)), (2, None, None))

    def test_the_first_time_the_party_is_stated_it_is_the_party(self):
        self.assertEqual(who(hear("just the two of us", party(None), adults=2)), (2, None, None))


# --- 3b. the merge on its own ----------------------------------------------------------------


class MergeOnItsOwnTests(SimpleTestCase):
    """The merge settles exactly one waiting person whatever called it: the guard decides what
    the words mean, but the merge is the one that must never settle two people at once or add an
    adult to a party nobody has described."""

    def merged(self, verdict, record):
        return apply_components(record, {**comps(), "pending_person": verdict}, TODAY)

    def test_it_settles_the_one_person_waiting(self):
        self.assertEqual(who(self.merged("adult", WAITING)), (3, 0, None))
        self.assertEqual(who(self.merged("not_coming", WAITING)), (2, 0, None))

    def test_it_never_settles_several_people_at_once(self):
        for verdict in ("adult", "not_coming", "unclear"):
            with self.subTest(verdict=verdict):
                applied = self.merged(verdict, party(2, 2))

                self.assertEqual(who(applied), (2, 2, None))
                self.assertEqual(issues_of(applied), ["pending_person_unclear"])

    def test_it_has_nobody_to_settle_when_nobody_is_waiting(self):
        applied = self.merged("not_coming", party(2, 1, [6]))

        self.assertEqual(who(applied), (2, 1, [6]))
        self.assertEqual(issues_of(applied), ["pending_person_unclear"])

    def test_it_adds_no_adult_to_a_party_nobody_described(self):
        applied = self.merged("adult", party(None, 1))

        self.assertEqual(who(applied), (None, 1, None))
        self.assertEqual(issues_of(applied), ["pending_person_unclear"])


# --- 4. what the reply is told ---------------------------------------------------------------


class FactsTests(SimpleTestCase):
    def facts_after(self, message, **model):
        applied = hear(message, WAITING, **model)
        return fact_block(
            TripTurn(
                trip=resolve(applied.record, TODAY),
                issues=applied.issues,
                ask_child_ages=applied.ask_child_ages,
                pending_resolved=applied.pending_resolved,
                today=TODAY,
            )
        )

    def test_an_adult_is_counted_and_the_reply_may_say_so(self):
        facts = self.facts_after("ele é adulto", adults=1)

        self.assertIn("is counted as one more adult now", facts)
        self.assertIn("Adults: 3.", facts)
        self.assertIn("carries exactly: dates 2026-12-05 to 2026-12-09, 3 adults", facts)

    def test_a_person_who_is_not_coming_is_no_longer_counted_and_nothing_else_changed(self):
        facts = self.facts_after("ele não vai mais")

        self.assertIn("is no longer counted", facts)
        self.assertIn("Nobody else in the party changed", facts)
        self.assertIn("Adults: 2.", facts)
        self.assertNotIn("Children:", facts)
        self.assertNotIn("age is not known", facts)  # no age is asked for any more
        self.assertIn("carries exactly: dates 2026-12-05 to 2026-12-09, 2 adults", facts)

    def test_an_unclear_answer_asks_one_question_and_never_calls_them_a_child(self):
        facts = self.facts_after("um adulto", adults=1)

        self.assertIn("not clearly enough to tell whether they are one more adult", facts)
        self.assertIn('never "your child"', facts)
        self.assertIn("There is NO Booking search action yet", facts)
        self.assertNotIn("counted as one more adult now", facts)


# --- 5. whole turns -------------------------------------------------------------------------------


class PendingPersonWholeTurnTests(_TripCase):
    def tab(self, provider):
        return ViewSession(
            self.user, ai_provider=provider, climate_provider=self.climate, save=False
        )

    def waiting(self, *later):
        """Barcelona chosen, a search ready for two adults - then a cousin joins with no age."""
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                stays(adults=2, **WHEN),
                turn(spain(), trip_details={"people_added": [{"kind": "unsure", "age": None}]}),
                *later,
            ]
        )
        tab = self.tab(provider)
        tab.post("quero ir pra Barcelona")
        ready = tab.post("hospedagem dia 5, 3 dias, somos 2")
        waiting = tab.post("e meu primo vai também")
        return provider, tab, ready, waiting

    def test_the_cousin_waiting_leaves_no_search_and_retires_the_old_button(self):
        _, _, ready, waiting = self.waiting()

        self.assertEqual(len(ready.cards), 1)
        self.assertEqual(waiting.cards, [])
        self.assertTrue(waiting.retire_stays)
        self.assertEqual((self.stored()["adults"], self.stored()["children"]), (2, 1))

    def test_he_is_an_adult_adds_one_adult_and_the_search_comes_back(self):
        provider, tab, _, _ = self.waiting(turn(spain(), trip_details={"adults": 1}))

        settled = tab.post("ele é adulto")

        (card,) = settled.cards
        self.assertEqual(query_of(card["accommodation_search_url"])[3:], [("group_adults", "3")])
        self.assertIn("3 adults", card["accommodation_caption"])
        self.assertNotIn("child", card["accommodation_caption"])
        self.assertTrue(settled.retire_stays)  # the page draws the new search over any old one
        stored = self.stored()
        self.assertEqual((stored["adults"], stored["children"], stored["child_ages"]), (3, 0, None))
        facts = self.prompt_of_last_reply(provider)
        self.assertIn("Adults: 3.", facts)
        self.assertIn("is counted as one more adult now", facts)

    def test_he_cannot_come_drops_him_and_the_search_comes_back_for_the_confirmed_party(self):
        provider, tab, _, _ = self.waiting(turn(spain()))
        calls_before = self.trip_calls(provider)

        settled = tab.post("ele não vai mais")

        # A message with no cue word in it is still read while a person is waiting.
        self.assertEqual(self.trip_calls(provider), calls_before + 1)
        (card,) = settled.cards
        self.assertEqual(query_of(card["accommodation_search_url"])[3:], [("group_adults", "2")])
        self.assertIn("2 adults", card["accommodation_caption"])
        self.assertNotIn("child", card["accommodation_caption"])
        self.assertTrue(settled.retire_stays)
        stored = self.stored()
        self.assertEqual((stored["adults"], stored["children"], stored["child_ages"]), (2, 0, None))
        facts = self.prompt_of_last_reply(provider)
        self.assertIn("is no longer counted", facts)
        self.assertNotIn("a child's age is missing", facts)

    def test_just_the_two_of_us_drops_him_too(self):
        provider, tab, _, _ = self.waiting(turn(spain(), trip_details={"adults": 2}))

        settled = tab.post("só nós dois")

        (card,) = settled.cards
        self.assertEqual(query_of(card["accommodation_search_url"])[3:], [("group_adults", "2")])
        self.assertEqual(self.stored()["children"], 0)

    def test_an_answer_that_could_mean_several_things_changes_nothing_and_asks(self):
        provider, tab, _, _ = self.waiting(turn(spain(), trip_details={"adults": 1}))

        asked = tab.post("um adulto")

        self.assertEqual(asked.cards, [])
        self.assertFalse(asked.retire_stays)  # nothing changed, so nothing on the page is stale
        stored = self.stored()
        self.assertEqual((stored["adults"], stored["children"]), (2, 1))
        facts = self.prompt_of_last_reply(provider)
        self.assertIn("not clearly enough to tell whether they are one more adult", facts)
        self.assertIn("There is NO Booking search action yet", facts)

    def test_the_age_still_settles_it_the_way_it_always_did(self):
        provider, tab, _, _ = self.waiting(
            turn(spain(), trip_details={"people_added": [{"kind": "unsure", "age": 25}]})
        )

        settled = tab.post("ele tem 25 anos")

        (card,) = settled.cards
        self.assertEqual(query_of(card["accommodation_search_url"])[3:], [("group_adults", "3")])

    def test_with_nobody_waiting_those_words_are_not_read_at_all(self):
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                stays(adults=2, **WHEN),
                turn(spain()),
            ]
        )
        tab = self.tab(provider)
        tab.post("quero ir pra Barcelona")
        tab.post("hospedagem dia 5, 3 dias, somos 2")
        calls_before = self.trip_calls(provider)

        tab.post("ele não vai mais")

        self.assertEqual(self.trip_calls(provider), calls_before)
        self.assertEqual(self.stored()["adults"], 2)
