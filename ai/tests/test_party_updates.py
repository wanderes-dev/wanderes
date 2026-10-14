"""The party on record, changed a piece at a time: one child's age corrected by pointing at the
child ("o mais novo fez 5"), another child, another adult.

The extraction reports these as components, and in practice it reports them together with
figures for a whole party (a correction next to `child_ages` and a count of one; an added child
as `children 1, ages [9]`). A party restated that way would replace the one on record, so the
cases here use the shapes the real model returned, labelled with the situation they came from,
as well as the clean ones - in Brazilian and European Portuguese, Spanish and English."""

from django.core.cache import cache
from django.test import SimpleTestCase

from ai.orchestration import _turn_index
from ai.tests.helpers import ScriptedProvider
from ai.tests.test_selected_destination import WHEN, spain, turn
from ai.tests.test_trip_details import TODAY, comps, record
from ai.tests.test_trip_details_flow import _TripCase, plain, query_of, stays
from ai.trip_details import (
    TRIP_DETAILS_SCHEMA,
    TRIP_DETAILS_SYSTEM_PROMPT,
    TripTurn,
    apply_components,
    fact_block,
    guard_components,
    has_trip_detail_cues,
    resolve,
    validate_components,
)
from evaluations.view_path import ViewSession


def party(adults=2, children=None, ages=None):
    """A stay already planned (5 December, 4 nights) for this party."""
    return record(
        start_date="2026-12-05",
        stay_length=4,
        stay_unit="nights",
        adults=adults,
        children=children,
        child_ages=ages,
    )


def hear(message, current, *, turn_key=None, **model):
    """What is stored when the extraction answers `model` to `message` on top of `current`: the
    guard first and then the merge, the two steps every real turn goes through."""
    guarded = guard_components(comps(**model), message, current)
    return apply_components(current, guarded, TODAY, turn=turn_key)


def who(applied):
    stored = applied.record or {}
    return stored.get("adults"), stored.get("children"), stored.get("child_ages")


def issues_of(applied):
    return [issue.code for issue in applied.issues]


def link_of(applied):
    return resolve(applied.record, TODAY).booking_kwargs()


# --- 1. a child's age corrected by pointing at the child -------------------------------------

# (label, language, record, message, what the extraction returned, (adults, children, ages))
POINTER_CASES = [
    # The model answers with the correction, the age again as `child_ages` and a count of one.
    (
        "older child to 19, several languages' shape",
        "es",
        party(2, 2, [6, 9]),
        "el mayor en realidad tiene 19",
        dict(children=1, ages=[19], correction={"to_age": 19}),
        (3, 1, [6]),
    ),
    (
        "youngest of three",
        "pt-br",
        party(2, 3, [4, 10, 13]),
        "o mais novo fez 5",
        dict(children=1, ages=[5], correction={"to_age": 5}),
        (2, 3, [5, 10, 13]),
    ),
    (
        "youngest of three, the model also said which",
        "pt-br",
        party(2, 3, [4, 10, 13]),
        "o mais novo fez 5",
        dict(children=1, ages=[5], correction={"to_age": 5, "which": "younger"}),
        (2, 3, [5, 10, 13]),
    ),
    (
        "the older of two",
        "es",
        party(2, 2, [6, 10]),
        "el mayor tiene 11",
        dict(children=1, ages=[11], correction={"to_age": 11}),
        (2, 2, [6, 11]),
    ),
    (
        "the younger of two",
        "pt-pt",
        party(2, 2, [3, 9]),
        "a mais nova tem 4",
        dict(children=1, ages=[4], correction={"to_age": 4}),
        (2, 2, [4, 9]),
    ),
    (
        "pointed at by the age it had",
        "en",
        party(2, 2, [6, 9]),
        "the 6 year old is actually 7",
        dict(children=1, ages=[7], correction={"to_age": 7}),
        (2, 2, [7, 9]),
    ),
    (
        "pointed at by the age it had, Spanish",
        "es",
        party(2, 2, [5, 10]),
        "el de 5 en realidad tiene 6",
        dict(children=1, ages=[6], correction={"to_age": 6}),
        (2, 2, [6, 10]),
    ),
    # The clean shapes.
    (
        "clean, the younger",
        "en",
        party(2, 2, [7, 12]),
        "make the younger one 6",
        dict(correction={"to_age": 6}),
        (2, 2, [6, 12]),
    ),
    (
        "clean, the older",
        "en",
        party(2, 2, [7, 12]),
        "the older one is now 13",
        dict(correction={"to_age": 13}),
        (2, 2, [7, 13]),
    ),
    (
        "clean, by the old age",
        "pt-br",
        party(2, 3, [4, 9, 13]),
        "o de 9 na verdade tem 10",
        dict(correction={"from_age": 9, "to_age": 10}),
        (2, 3, [4, 10, 13]),
    ),
    # The age alone, with the pointer in the words: the oldest legacy shape.
    (
        "the age alone, younger in the words",
        "pt-br",
        party(2, 2, [7, 12]),
        "o mais novo tem 8",
        dict(children=1, ages=[8]),
        (2, 2, [8, 12]),
    ),
    (
        "smaller and larger words",
        "es",
        party(2, 2, [3, 8]),
        "el menor tiene 4",
        dict(children=1, ages=[4], correction={"to_age": 4}),
        (2, 2, [4, 8]),
    ),
    (
        "the elder, feminine",
        "es",
        party(2, 2, [3, 8]),
        "la mayor tiene 9",
        dict(children=1, ages=[9], correction={"to_age": 9}),
        (2, 2, [3, 9]),
    ),
    (
        "the oldest, European Portuguese",
        "pt-pt",
        party(2, 2, [5, 9]),
        "o mais velho fez 10 anos",
        dict(children=1, ages=[10], correction={"to_age": 10}),
        (2, 2, [5, 10]),
    ),
    (
        "the middle one",
        "pt-br",
        party(2, 3, [4, 7, 12]),
        "o do meio fez 8",
        dict(children=1, ages=[8], correction={"to_age": 8}),
        (2, 3, [4, 8, 12]),
    ),
    (
        "the only child, pointed at as the youngest",
        "pt-br",
        party(2, 1, [6]),
        "a mais nova tem 7",
        dict(children=1, ages=[7], correction={"to_age": 7}),
        (2, 1, [7]),
    ),
    # The extraction found nothing at all in a message that points at a child and gives an age.
    (
        "nothing returned, the middle one",
        "pt-br",
        party(2, 3, [4, 7, 13]),
        "o do meio tem 8 na verdade",
        dict(),
        (2, 3, [4, 8, 13]),
    ),
    (
        "the new age given as the old one, and the wrong child named",
        "pt-br",
        party(2, 3, [4, 7, 13]),
        "o do meio tem 8 na verdade",
        dict(correction={"from_age": 8, "to_age": 8, "which": "younger"}),
        (2, 3, [4, 8, 13]),
    ),
    (
        "an old age the model made up, that the message never said",
        "pt-br",
        party(2, 3, [4, 10, 13]),
        "o mais novo fez 5",
        dict(correction={"from_age": 7, "to_age": 5, "which": "younger"}),
        (2, 3, [5, 10, 13]),
    ),
    (
        "nothing returned, turned",
        "es",
        party(2, 2, [3, 8]),
        "la menor cumplió 5",
        dict(),
        (2, 2, [5, 8]),
    ),
]


class PointerCorrectionTests(SimpleTestCase):
    def test_the_child_the_message_points_at_gets_the_new_age_and_nobody_else_changes(self):
        for label, _language, current, message, model, expected in POINTER_CASES:
            with self.subTest(label=label, message=message):
                applied = hear(message, current, **model)

                self.assertEqual(issues_of(applied), [])
                self.assertEqual(who(applied), expected)
                self.assertTrue(applied.details_changed)
                self.assertFalse(applied.ask_child_ages)
                # the dates and the length of the stay are exactly as they were
                self.assertEqual(applied.record["start_date"], "2026-12-05")
                self.assertEqual(applied.record["stay_length"], 4)

    def test_the_search_carries_the_corrected_party(self):
        applied = hear(
            "o mais novo fez 5",
            party(2, 3, [4, 10, 13]),
            children=1,
            ages=[5],
            correction={"to_age": 5},
        )

        kwargs = link_of(applied)

        self.assertEqual(kwargs["adults"], 2)
        self.assertEqual(kwargs["children"], 3)
        self.assertEqual(kwargs["child_ages"], [5, 10, 13])

    def test_the_merge_alone_handles_the_hybrid_when_the_model_named_the_child(self):
        # Without the guard: the correction, the age again and a count of one, with `which` set.
        applied = apply_components(
            party(2, 3, [4, 10, 13]),
            comps(children=1, ages=[5], correction={"to_age": 5, "which": "younger"}),
            TODAY,
        )

        self.assertEqual(who(applied), (2, 3, [5, 10, 13]))
        self.assertEqual(issues_of(applied), [])

    def test_the_merge_alone_never_collapses_the_party_when_it_cannot_tell_which_child(self):
        applied = apply_components(
            party(2, 2, [7, 12]),
            comps(children=1, ages=[9], correction={"to_age": 9}),
            TODAY,
        )

        self.assertEqual(who(applied), (2, 2, [7, 12]))
        self.assertEqual(issues_of(applied), ["ambiguous_age_correction"])


class PointerAmbiguityTests(SimpleTestCase):
    """When the words do not single out one child, the traveler is asked and nothing changes -
    not even the number of children."""

    def assert_asked_and_unchanged(self, applied, current):
        self.assertEqual(issues_of(applied), ["ambiguous_age_correction"])
        self.assertEqual(
            who(applied), (current["adults"], current["children"], current["child_ages"])
        )
        self.assertFalse(applied.details_changed)
        self.assertEqual(applied.record["start_date"], current["start_date"])

    def test_an_age_with_nothing_pointing_anywhere_is_a_question(self):
        current = party(2, 2, [7, 12])
        for label, model in (
            ("pure", dict(correction={"to_age": 9})),
            ("hybrid", dict(children=1, ages=[9], correction={"to_age": 9})),
            ("the age alone", dict(children=1, ages=[9])),
        ):
            with self.subTest(label=label):
                self.assert_asked_and_unchanged(hear("ela tem 9 anos", current, **model), current)

    def test_an_old_age_no_child_has_is_a_question(self):
        current = party(2, 2, [7, 12])

        applied = hear(
            "el de 8 en realidad tiene 9", current, children=1, ages=[9], correction={"to_age": 9}
        )

        self.assert_asked_and_unchanged(applied, current)

    def test_twins_cannot_be_told_apart_by_younger_or_older(self):
        current = party(2, 2, [5, 5])
        for message, model in (
            ("o mais novo tem 6", dict(children=1, ages=[6], correction={"to_age": 6})),
            ("the older one is 6", dict(correction={"to_age": 6, "which": "older"})),
        ):
            with self.subTest(message=message):
                self.assert_asked_and_unchanged(hear(message, current, **model), current)

    def test_the_same_old_age_on_two_children_is_a_question(self):
        current = party(2, 2, [6, 6])

        applied = hear(
            "o de 6 agora tem 7", current, children=1, ages=[7], correction={"to_age": 7}
        )

        self.assert_asked_and_unchanged(applied, current)

    def test_the_middle_one_needs_three_children(self):
        for current in (party(2, 1, [6]), party(2, 2, [6, 9]), party(2, 3, [4, 7, 7])):
            with self.subTest(children=current["children"]):
                applied = hear("o do meio fez 8", current, correction={"to_age": 8})

                self.assert_asked_and_unchanged(applied, current)

    def test_a_pointer_the_model_made_up_is_not_followed(self):
        # The extraction answered "the younger one" to a message with no word that points at a
        # child: the child changed silently. The words decide, the traveler is asked.
        current = party(2, 2, [6, 10])

        applied = hear(
            "afinal uma delas tem 8",
            current,
            children=1,
            ages=[8],
            correction={"to_age": 8, "which": "younger"},
        )

        self.assert_asked_and_unchanged(applied, current)

    def test_the_other_one_is_a_pointer_nobody_can_follow(self):
        current = party(2, 2, [6, 9])

        applied = hear("a outra criança tem 7 anos", current, children=1, ages=[7])

        self.assert_asked_and_unchanged(applied, current)

    def test_the_question_is_the_one_the_reply_asks(self):
        current = party(2, 2, [7, 12])
        applied = hear("ela tem 9 anos", current, children=1, ages=[9], correction={"to_age": 9})
        facts = fact_block(
            TripTurn(trip=resolve(applied.record, TODAY), issues=applied.issues, today=TODAY)
        )

        self.assertIn("it is not clear which child", facts)
        self.assertIn("Nothing was changed. Ask which child they mean.", facts)
        self.assertIn("Children: 2, ages 7, 12", facts)  # the party the link still carries


class ChildBecomesAdultTests(SimpleTestCase):
    def test_the_older_child_corrected_to_19_is_an_adult_and_the_counts_follow(self):
        for message, model in (
            (
                "el mayor en realidad tiene 19",
                dict(children=1, ages=[19], correction={"to_age": 19}),
            ),
            ("el mayor en realidad tiene 19", dict(correction={"to_age": 19})),
        ):
            with self.subTest(model=model):
                applied = hear(message, party(2, 2, [6, 9]), **model)

                self.assertEqual(who(applied), (3, 1, [6]))
                kwargs = link_of(applied)
                self.assertEqual(
                    (kwargs["adults"], kwargs["children"], kwargs["child_ages"]), (3, 1, [6])
                )

    def test_the_only_child_becoming_an_adult_leaves_no_children(self):
        applied = hear(
            "el mayor tiene 19", party(2, 1, [10]), children=1, ages=[19], correction={"to_age": 19}
        )

        self.assertEqual(who(applied), (3, 0, None))
        self.assertEqual(link_of(applied)["adults"], 3)
        self.assertNotIn("children", link_of(applied))

    def test_the_middle_child_becoming_an_adult(self):
        applied = hear(
            "the middle one is 18 now",
            party(2, 3, [4, 10, 13]),
            correction={"to_age": 18, "which": "middle"},
        )

        self.assertEqual(who(applied), (3, 2, [4, 13]))

    def test_the_younger_child_becoming_an_adult(self):
        applied = hear(
            "a mais nova tem 18",
            party(2, 2, [6, 9]),
            children=1,
            ages=[18],
            correction={"to_age": 18},
        )

        self.assertEqual(who(applied), (3, 1, [9]))

    def test_it_happens_once_even_when_the_turn_runs_twice(self):
        message, model = (
            "el mayor en realidad tiene 19",
            dict(children=1, ages=[19], correction={"to_age": 19}),
        )
        first = hear(message, party(2, 2, [6, 9]), turn_key=11, **model)

        again = hear(message, first.record, turn_key=11, **model)
        later = hear(message, first.record, turn_key=12, **model)

        self.assertEqual(who(first), (3, 1, [6]))
        self.assertEqual(who(again), (3, 1, [6]))  # the retry changes nothing
        self.assertEqual(who(later), (4, 0, None))  # a new turn is a new message


class CorrectionLeavesTheRestAloneTests(SimpleTestCase):
    def test_an_age_is_never_a_date_or_a_length_of_stay(self):
        current = party(2, 2, [7, 12])

        applied = hear(
            "o mais velho tem 13",
            current,
            children=1,
            ages=[13],
            correction={"to_age": 13},
            day=13,
            length=13,
            unit="days",
            change={"nights_delta": 1},
        )

        self.assertEqual(who(applied), (2, 2, [7, 13]))
        self.assertEqual(applied.record["start_date"], "2026-12-05")
        self.assertEqual(applied.record["stay_length"], 4)

    def test_dates_in_the_same_message_are_still_read(self):
        applied = hear(
            "o mais velho tem 13 e ficamos mais uma noite",
            party(2, 2, [7, 12]),
            correction={"to_age": 13},
            change={"nights_delta": 1},
        )

        self.assertEqual(who(applied), (2, 2, [7, 13]))
        self.assertEqual(applied.record["stay_length"], 5)

    def test_saying_an_age_a_child_already_has_changes_nothing(self):
        current = party(2, 2, [3, 9])

        applied = hear("a mais nova tem 3", current, children=1, ages=[3], correction={"to_age": 3})

        self.assertEqual(who(applied), (2, 2, [3, 9]))
        self.assertEqual(issues_of(applied), [])
        self.assertFalse(applied.details_changed)

    def test_rooms_and_the_adults_are_untouched(self):
        current = {**party(3, 2, [6, 9]), "rooms": 2}

        applied = hear(
            "el mayor tiene 10", current, children=1, ages=[10], correction={"to_age": 10}
        )

        self.assertEqual(who(applied), (3, 2, [6, 10]))
        self.assertEqual(applied.record["rooms"], 2)


# --- 2. another child -------------------------------------------------------------------------

# (label, language, message, what the extraction returned, the new child's age)
ADD_CHILD_CASES = [
    # The shapes the real model returned for these: the new child's figures as the whole party.
    ("pt-br, age", "pt-br", "e mais uma criança de 9 anos", dict(children=1, ages=[9]), 9),
    (
        "pt-br, daughter, an adult counted by default",
        "pt-br",
        "vamos levar também a minha filha de 9 anos",
        dict(adults=1, children=1, ages=[9]),
        9,
    ),
    ("pt-pt", "pt-pt", "e mais um miúdo de 9 anos", dict(children=1, ages=[9]), 9),
    ("es, también", "es", "y también un niño de 9 años", dict(children=1, ages=[9]), 9),
    ("en, another", "en", "and another child aged 5", dict(children=1, ages=[5]), 5),
    (
        "en, bringing",
        "en",
        "and we're also bringing another kid, he's 9",
        dict(children=1, ages=[9]),
        9,
    ),
    ("en, one more", "en", "one more child, 9 years old", dict(children=1, ages=[9]), 9),
    ("en, plus", "en", "plus a 4 year old", dict(children=1, ages=[4]), 4),
    ("es, una más", "es", "y una más de 6 años", dict(children=1, ages=[6]), 6),
    (
        "pt-pt, junta-se",
        "pt-pt",
        "junta-se a nós mais uma miúda, de 5 anos",
        dict(children=1, ages=[5]),
        5,
    ),
    ("es, se agrega", "es", "se agrega un nene de 4 años", dict(added=[("child", 4)]), 4),
    (
        "es, se incorpora",
        "es",
        "se incorpora un primito de 3 años",
        dict(children=1, ages=[3], added=[("child", 3)]),
        3,
    ),
    (
        "pt-br, along, with a diminutive",
        "pt-br",
        "ah, e a minha filhota de 2 anos vai junto",
        dict(children=1, ages=[2]),
        2,
    ),
    ("en, add", "en", "add one more kid, he's 7", dict(added=[("child", 7)]), 7),
    (
        "pt-br, godson",
        "pt-br",
        "levaremos também o meu afilhado de 12 anos",
        dict(children=1, ages=[12]),
        12,
    ),
    # The same with the addition reported as such (and the whole-party figures beside it).
    (
        "pt-br, reported",
        "pt-br",
        "e mais uma criança de 9 anos",
        dict(children=1, ages=[9], added=[("child", 9)]),
        9,
    ),
    (
        "pt-br, other child",
        "pt-br",
        "também vai outra criança de 8",
        dict(children=1, ages=[8], added=[("child", 8)]),
        8,
    ),
    ("es, otra", "es", "y otra niña de 6", dict(children=1, ages=[6], added=[("child", 6)]), 6),
    ("es, se suma", "es", "se suma otra niña de 5 años", dict(added=[("child", 5)]), 5),
    (
        "en, reported",
        "en",
        "and another child aged 5",
        dict(children=1, ages=[5], added=[("child", 5)]),
        5,
    ),
]


class AddChildTests(SimpleTestCase):
    def test_the_new_child_joins_the_children_on_record(self):
        for label, _language, message, model, age in ADD_CHILD_CASES:
            with self.subTest(label=label, message=message):
                applied = hear(message, party(2, 1, [6]), **model)

                self.assertEqual(issues_of(applied), [])
                self.assertEqual(who(applied), (2, 2, [6, age]))
                self.assertFalse(applied.ask_child_ages)
                self.assertEqual(applied.record["start_date"], "2026-12-05")
                self.assertEqual(applied.record["stay_length"], 4)
                kwargs = link_of(applied)
                self.assertEqual(
                    (kwargs["adults"], kwargs["children"], kwargs["child_ages"]),
                    (2, 2, [6, age]),
                )

    def test_a_third_child_is_added_to_two(self):
        # The shape the real model returned: one child aged 13, said to be among those counted.
        for label, model in (
            ("among", dict(children=1, ages=[13], among=True)),
            ("reported", dict(children=1, ages=[13], added=[("child", 13)])),
            ("age only", dict(added=[("child", 13)])),
        ):
            with self.subTest(label=label):
                applied = hear("e mais uma de 13 anos", party(2, 2, [4, 9]), **model)

                self.assertEqual(who(applied), (2, 3, [4, 9, 13]))
                self.assertEqual(issues_of(applied), [])

    def test_an_added_child_is_never_a_replacement(self):
        # The defect: "children 1, ages [9]" read as the whole set replaced the first child.
        applied = hear("e mais uma criança de 9 anos", party(2, 1, [6]), children=1, ages=[9])

        self.assertNotEqual(who(applied), (2, 1, [9]))
        self.assertEqual(who(applied)[2], [6, 9])

    def test_an_age_read_as_a_stay_length_or_a_date_changes_neither(self):
        applied = hear(
            "e mais uma de 13 anos",
            party(2, 1, [6]),
            children=1,
            ages=[13],
            added=[("child", 13)],
            length=13,
            unit="days",
            day=13,
        )

        self.assertEqual(who(applied), (2, 2, [6, 13]))
        self.assertEqual(applied.record["stay_length"], 4)
        self.assertEqual(applied.record["start_date"], "2026-12-05")

    def test_one_more_child_is_not_one_more_night(self):
        applied = hear(
            "e mais uma criança",
            party(2, 1, [6]),
            children=1,
            added=[("child", None)],
            change={"nights_delta": 1},
        )

        self.assertEqual(applied.record["stay_length"], 4)
        self.assertEqual(who(applied), (2, 2, [6]))

    def test_it_happens_once_when_the_turn_runs_twice(self):
        message, model = "e mais uma criança de 9 anos", dict(children=1, ages=[9])
        first = hear(message, party(2, 1, [6]), turn_key=4, **model)

        again = hear(message, first.record, turn_key=4, **model)
        next_turn = hear(message, first.record, turn_key=5, **model)

        self.assertEqual(who(first), (2, 2, [6, 9]))
        self.assertEqual(who(again), (2, 2, [6, 9]))
        self.assertEqual(who(next_turn), (2, 3, [6, 9, 9]))

    def test_an_adult_age_makes_an_adult_not_a_child(self):
        applied = hear(
            "e mais uma de 25 anos", party(2, 1, [6]), children=1, ages=[25], added=[("child", 25)]
        )

        self.assertEqual(who(applied), (3, 1, [6]))


class AddChildWithoutAnAgeTests(SimpleTestCase):
    """The party on record is kept and the missing age is asked for - the search waits."""

    MESSAGES = (
        ("pt-br", "e mais uma criança"),
        ("es", "y otro niño"),
        ("en", "we're also bringing another child"),
    )

    def test_the_child_is_added_with_no_age_and_the_others_keep_theirs(self):
        for language, message in self.MESSAGES:
            with self.subTest(language=language):
                applied = hear(message, party(2, 1, [6]), children=1, added=[("child", None)])

                self.assertEqual(who(applied), (2, 2, [6]))
                self.assertTrue(applied.ask_child_ages)
                trip = resolve(applied.record, TODAY)
                self.assertEqual(trip.missing_for_search, ("child_ages",))
                self.assertIsNone(trip.search_kwargs())

    def test_the_words_alone_add_it_when_the_model_returned_only_a_count(self):
        applied = hear("e mais uma criança", party(2, 1, [6]), children=1)

        self.assertEqual(who(applied), (2, 2, [6]))
        self.assertTrue(applied.ask_child_ages)

    def test_the_age_that_comes_next_completes_the_set_without_replacing_anyone(self):
        waiting = hear("e mais uma criança", party(2, 1, [6]), children=1, added=[("child", None)])

        for message, model in (
            ("tem 9 anos", dict(ages=[9])),
            ("9 anos", dict(ages=[9])),
            ("she's 9", dict(ages=[9])),
        ):
            with self.subTest(message=message):
                done = hear(message, waiting.record, **model)

                self.assertEqual(who(done), (2, 2, [6, 9]))
                self.assertEqual(resolve(done.record, TODAY).missing_for_search, ())

    def test_a_child_with_an_age_joining_a_child_with_none_waits_for_the_first_age(self):
        applied = hear(
            "e mais uma criança de 9 anos",
            party(2, 1, None),
            children=1,
            ages=[9],
            added=[("child", 9)],
        )

        self.assertEqual(who(applied), (2, 2, [9]))
        self.assertTrue(applied.ask_child_ages)

    def test_the_facts_ask_only_for_the_missing_age(self):
        applied = hear("e mais uma criança", party(2, 1, [6]), children=1, added=[("child", None)])

        facts = fact_block(
            TripTurn(
                trip=resolve(applied.record, TODAY),
                issues=applied.issues,
                ask_child_ages=applied.ask_child_ages,
                today=TODAY,
            )
        )

        self.assertIn("the ages known so far are 6", facts)
        self.assertIn("ask only for the missing one(s)", facts)


# --- 3. another adult -------------------------------------------------------------------------

# (label, language, message, what the extraction returned, adults afterwards)
ADD_ADULT_CASES = [
    ("a friend", "pt-br", "vai mais um amigo", dict(added=[("adult", None)]), 3),
    (
        "a friend, a head count of one beside it",
        "pt-br",
        "vai mais um amigo",
        dict(adults=1, added=[("adult", None)]),
        3,
    ),
    ("another adult", "en", "another adult is joining us", dict(added=[("adult", None)]), 3),
    ("otro adulto", "es", "se suma otro adulto", dict(added=[("adult", None)]), 3),
    ("pt-pt", "pt-pt", "e mais um adulto", dict(added=[("adult", None)]), 3),
    ("two friends", "pt-br", "vão mais dois amigos", dict(added=[("adult", None)] * 2), 4),
    ("two friends, es", "es", "y se suman dos amigos más", dict(added=[("adult", None)] * 2), 4),
    ("two friends, en", "en", "two more friends are coming", dict(added=[("adult", None)] * 2), 4),
    (
        "a sister of 25",
        "pt-br",
        "também vem a minha irmã de 25 anos",
        dict(added=[("unsure", 25)]),
        3,
    ),
    (
        "a cousin of 25",
        "en",
        "and my cousin is joining us, he's 25",
        dict(added=[("unsure", 25)]),
        3,
    ),
    (
        "a sister of 30, es",
        "es",
        "mi hermana también viene, tiene 30",
        dict(added=[("unsure", 30)]),
        3,
    ),
    # Relatives who are grown-ups: no age needed.
    ("a mother", "pt-br", "minha mãe também vai", dict(added=[("unsure", None)]), 3),
    ("an uncle", "es", "y mi tío también viene", dict(added=[("unsure", None)]), 3),
    ("a grandmother", "pt-pt", "e a minha avó também vai", dict(added=[("unsure", None)]), 3),
    ("parents", "en", "my parents are coming too", dict(added=[("adult", None)] * 2), 4),
]


class AddAdultTests(SimpleTestCase):
    def test_the_adult_joins_the_adults_on_record(self):
        for label, _language, message, model, adults in ADD_ADULT_CASES:
            with self.subTest(label=label, message=message):
                applied = hear(message, party(2), **model)

                self.assertEqual(issues_of(applied), [])
                self.assertEqual(who(applied), (adults, None, None))
                self.assertFalse(applied.ask_child_ages)
                self.assertEqual(link_of(applied)["adults"], adults)
                self.assertEqual(applied.record["start_date"], "2026-12-05")
                self.assertEqual(applied.record["stay_length"], 4)

    def test_nobody_on_record_is_reduced_or_replaced(self):
        applied = hear("vai mais um amigo", party(2, 2, [6, 9]), adults=1, added=[("adult", None)])

        self.assertEqual(who(applied), (3, 2, [6, 9]))
        self.assertEqual(link_of(applied)["child_ages"], [6, 9])

    def test_a_friend_aged_under_18_is_a_child_with_that_age(self):
        applied = hear("vai mais um amigo de 15 anos", party(2), added=[("adult", 15)])

        self.assertEqual(who(applied), (2, 1, [15]))

    def test_it_happens_once_when_the_turn_runs_twice(self):
        message, model = "vai mais um amigo", dict(added=[("adult", None)])
        first = hear(message, party(2), turn_key=7, **model)

        again = hear(message, first.record, turn_key=7, **model)
        next_turn = hear(message, first.record, turn_key=8, **model)

        self.assertEqual(who(first)[0], 3)
        self.assertEqual(who(again)[0], 3)
        self.assertEqual(who(next_turn)[0], 4)

    def test_an_age_read_as_a_stay_length_changes_nothing(self):
        applied = hear(
            "também vem a minha irmã de 25 anos",
            party(2),
            added=[("unsure", 25)],
            length=25,
            unit="days",
        )

        self.assertEqual(applied.record["stay_length"], 4)

    def test_the_words_alone_add_the_adult_when_the_model_returned_a_head_count(self):
        applied = hear("vai mais um amigo", party(2), adults=1)

        self.assertEqual(who(applied)[0], 3)

    def test_who_joins_waits_when_nobody_is_going_yet(self):
        applied = hear("vai mais um amigo", None, added=[("adult", None)])

        self.assertEqual(issues_of(applied), ["addition_without_party"])
        self.assertIsNone(applied.record)
        facts = fact_block(
            TripTurn(trip=resolve(applied.record, TODAY), issues=applied.issues, today=TODAY)
        )
        self.assertIn("nothing to add them to", facts)

    def test_a_person_next_to_a_verb_of_coming_is_added_even_with_no_join_word(self):
        # The model answered with the stored head count: "2 adults" for "viene mi prometida".
        for message, adults in (
            ("viene mi prometida", 3),
            ("o meu pai vai", 3),
            ("my mother is coming", 3),
            ("vem a minha tia", 3),
        ):
            with self.subTest(message=message):
                applied = hear(message, party(2), adults=2)

                self.assertEqual(who(applied)[0], adults)

    def test_the_traveler_speaking_of_themselves_or_where_someone_is_from_adds_nobody(self):
        for message in (
            "eu vou e a minha esposa vai",
            "yo voy y mi mujer viene",
            "meu primo vem de São Paulo",
            "my cousin comes from Madrid",
        ):
            with self.subTest(message=message):
                applied = hear(message, party(2), adults=2)

                self.assertEqual(who(applied)[0], 2)

    def test_with_several_people_reported_the_words_do_not_relabel_any_of_them(self):
        # An adult godmother and her daughter: the one noun in the message is the daughter's.
        applied = hear(
            "a minha comadre também vem, com a filha de 4",
            party(2, 1, [8]),
            added=[("adult", None), ("child", 4)],
        )

        self.assertEqual(issues_of(applied), [])
        self.assertEqual(who(applied), (3, 2, [8, 4]))

    def test_a_party_that_would_be_too_large_is_a_question(self):
        applied = hear("vai mais um amigo", party(30), added=[("adult", None)])

        self.assertEqual(issues_of(applied), ["party_too_large"])
        self.assertEqual(who(applied)[0], 30)


class OneAgeForTheOnlyChildTests(SimpleTestCase):
    """One age that differs from the only child's: the same child corrected, or another child?"""

    ONLY = party(2, 1, [4])

    def test_with_nothing_to_say_which_the_traveler_is_asked_and_nothing_is_replaced(self):
        # The shapes the real model returned: figures for one child aged 2, no person reported.
        for message, model in (
            ("ah, e a minha filhota de 2 anos", dict(children=1, ages=[2])),
            ("a minha filha tem 2 anos", dict(children=1, ages=[2])),
            ("o nosso filho de 19 anos", dict(children=1, ages=[19])),
        ):
            with self.subTest(message=message):
                applied = hear(message, self.ONLY, **model)

                self.assertEqual(who(applied), (2, 1, [4]))
                self.assertIn("age_or_new_child", issues_of(applied))

    def test_what_points_at_the_child_corrects_it(self):
        for message, model in (
            ("ela tem 2 anos", dict(children=1, ages=[2])),
            ("tem 2 anos", dict(ages=[2])),
            ("na verdade tem 2 anos", dict(children=1, ages=[2])),
            ("a criança tem 2 anos", dict(children=1, ages=[2])),
            ("o de 4 tem 2", dict(children=1, ages=[2])),
            ("actually she's 2", dict(children=1, ages=[2])),
        ):
            with self.subTest(message=message):
                applied = hear(message, self.ONLY, **model)

                self.assertEqual(who(applied), (2, 1, [2]))
                self.assertEqual(issues_of(applied), [])

    def test_the_cue_words_make_it_an_addition(self):
        for message in (
            "ah, e a minha filhota de 2 anos também vai",
            "e mais uma de 2 anos",
            "vai junto a minha filhinha de 2 anos",
        ):
            with self.subTest(message=message):
                applied = hear(message, self.ONLY, children=1, ages=[2])

                self.assertEqual(who(applied), (2, 2, [4, 2]))

    def test_the_question_is_the_one_the_reply_asks(self):
        applied = hear("a minha filha tem 2 anos", self.ONLY, children=1, ages=[2])

        facts = fact_block(
            TripTurn(trip=resolve(applied.record, TODAY), issues=applied.issues, today=TODAY)
        )

        self.assertIn("the same child with the new age, or one more child", facts)


class UnclearRelativeTests(SimpleTestCase):
    """A cousin, a brother, a niece: the age decides, so no age is assumed."""

    def test_the_question_names_who_joined_and_never_calls_them_a_child(self):
        applied = hear("my brother is coming too", party(2), added=[("unsure", None)])

        facts = fact_block(
            TripTurn(
                trip=resolve(applied.record, TODAY),
                ask_child_ages=applied.ask_child_ages,
                pending_relative=applied.pending_relative,
                today=TODAY,
            )
        )

        self.assertTrue(applied.pending_relative)
        self.assertIn('never "your child"', facts)

    def test_an_ordinary_child_without_an_age_is_still_a_child(self):
        applied = hear("e mais uma criança", party(2, 1, [6]), children=1, added=[("child", None)])

        self.assertFalse(applied.pending_relative)

    MESSAGES = (
        ("pt-br", "e meu primo vai também"),
        ("en", "my brother is coming too"),
        ("es", "mi hermano también viene"),
        ("pt-pt", "a minha sobrinha também vai"),
    )

    def test_without_an_age_the_search_waits_and_the_reply_asks(self):
        for language, message in self.MESSAGES:
            with self.subTest(language=language):
                applied = hear(message, party(2), added=[("unsure", None)])

                self.assertEqual(who(applied), (2, 1, None))  # no adult is assumed
                self.assertTrue(applied.ask_child_ages)
                self.assertIsNone(resolve(applied.record, TODAY).search_kwargs())

    def test_the_age_that_comes_next_decides_what_they_are(self):
        waiting = hear("e meu primo vai também", party(2), added=[("unsure", None)])

        grown = hear("ele tem 25 anos", waiting.record, ages=[25])
        young = hear("ele tem 12 anos", waiting.record, ages=[12])

        self.assertEqual(who(grown), (3, 0, None))
        self.assertEqual(resolve(grown.record, TODAY).missing_for_search, ())
        self.assertEqual(who(young), (2, 1, [12]))
        self.assertEqual(resolve(young.record, TODAY).missing_for_search, ())

    def test_the_age_is_taken_in_whatever_shape_the_model_answered(self):
        waiting = hear("e meu primo vai também", party(2), added=[("unsure", None)])

        for label, message, model, expected in (
            # The shapes the real model returned for these replies.
            ("as one more person", "ele tem 25 anos", dict(added=[("unsure", 25)]), (3, 0, None)),
            (
                "as a correction and a head count",
                "he's 30",
                dict(adults=1, correction={"to_age": 30, "which": "older"}),
                (3, 0, None),
            ),
            (
                "as a child and the age",
                "she's 12 years old",
                dict(children=1, ages=[12]),
                (2, 1, [12]),
            ),
            ("as the age alone", "tem 9", dict(ages=[9]), (2, 1, [9])),
            ("an adult, with the verb and no unit", "tiene 40", dict(ages=[40]), (3, 0, None)),
        ):
            with self.subTest(label=label, message=message):
                done = hear(message, waiting.record, **model)

                self.assertEqual(issues_of(done), [])
                self.assertEqual(who(done), expected)
                self.assertEqual(resolve(done.record, TODAY).missing_for_search, ())

    def test_the_old_button_would_be_retired_while_they_wait(self):
        before = resolve(party(2), TODAY).search_kwargs()
        applied = hear("e meu primo vai também", party(2), added=[("unsure", None)])

        self.assertIsNotNone(before)
        self.assertIsNone(resolve(applied.record, TODAY).search_kwargs())


class NotAnAdditionTests(SimpleTestCase):
    """What the guard holds back, so that a restated party or a stray mention adds nobody."""

    def test_a_party_restated_as_a_whole_replaces_the_one_on_record(self):
        applied = hear(
            "na verdade são duas crianças, de 6 e 9 anos",
            party(2, 1, [6]),
            children=2,
            ages=[6, 9],
        )

        self.assertEqual(who(applied), (2, 2, [6, 9]))

    def test_the_first_time_the_party_is_stated_nothing_is_added_to_it(self):
        applied = hear(
            "somos 2 adultos e mais uma criança de 6 anos",
            None,
            adults=2,
            children=1,
            ages=[6],
            added=[("child", 6)],
        )

        self.assertEqual(who(applied), (2, 1, [6]))

    def test_someone_joining_in_words_that_do_not_say_so_is_a_question(self):
        current = party(2, 1, [6])

        applied = hear(
            "vamos levar a minha filha de 9 anos",
            current,
            children=1,
            ages=[9],
            added=[("child", 9)],
        )

        self.assertEqual(issues_of(applied), ["addition_unclear"])
        self.assertEqual(who(applied), (2, 1, [6]))  # not replaced, not added to
        self.assertFalse(applied.details_changed)

    def test_an_addition_with_no_join_word_is_a_question_even_with_no_figures_beside_it(self):
        # The model reported someone joining where the words say where a cousin is from.
        for message in ("meu primo vem de São Paulo", "my cousin comes from Madrid"):
            with self.subTest(message=message):
                applied = hear(message, party(2, 1, [6]), added=[("unsure", None)])

                self.assertEqual(issues_of(applied), ["addition_unclear"])
                self.assertEqual(who(applied), (2, 1, [6]))

    def test_an_addition_that_names_nobody_is_a_question(self):
        applied = hear("vamos conhecer Lisboa", party(2), added=[("adult", None)])

        self.assertEqual(issues_of(applied), ["addition_unclear"])
        self.assertEqual(who(applied)[0], 2)

    def test_figures_that_say_more_than_the_people_reported_are_a_question(self):
        # "my cousin and his 5 year old are joining us", reported as the cousin alone with the
        # child's age left among the party's figures: two people joined, one was reported.
        current = party(2)

        applied = hear(
            "my cousin and his 5 year old are joining us",
            current,
            children=1,
            ages=[5],
            added=[("unsure", None)],
        )

        self.assertEqual(issues_of(applied), ["addition_unclear"])
        self.assertEqual(who(applied), (2, None, None))

    def test_figures_that_only_repeat_the_people_reported_are_not_a_question(self):
        for label, added, model in (
            ("a baby", [("child", 0)], dict(children=1, ages=[0])),
            ("a grown child", [("child", 25)], dict(children=1, ages=[25])),
            ("one child, no age", [("child", None)], dict(children=1)),
            ("two children", [("child", 4), ("child", 7)], dict(children=2, ages=[4, 7])),
        ):
            with self.subTest(label=label):
                applied = hear(
                    "e mais uma criança, vão também", party(2, 1, [6]), added=added, **model
                )

                self.assertEqual(issues_of(applied), [])

    def test_a_total_next_to_an_addition_is_a_question(self):
        applied = hear("somos 3 e vai mais um amigo", party(2), adults=3, added=[("adult", None)])

        self.assertEqual(issues_of(applied), ["addition_unclear"])
        self.assertEqual(who(applied)[0], 2)

    def test_the_question_for_an_unclear_addition_asks_for_the_totals(self):
        applied = hear(
            "vamos levar a minha filha de 9 anos",
            party(2, 1, [6]),
            children=1,
            ages=[9],
            added=[("child", 9)],
        )

        facts = fact_block(
            TripTurn(trip=resolve(applied.record, TODAY), issues=applied.issues, today=TODAY)
        )

        self.assertIn("Nothing was changed. Ask how many adults and how many children", facts)

    def test_a_friend_mentioned_in_passing_adds_nobody(self):
        applied = hear("meus amigos também recomendaram Lisboa", party(2))

        self.assertEqual(who(applied), (2, None, None))
        self.assertEqual(issues_of(applied), [])
        self.assertFalse(applied.details_changed)

    def test_one_more_night_is_still_a_longer_stay_and_not_a_person(self):
        applied = hear("mais uma noite", party(2, 1, [6]), change={"nights_delta": 1})

        self.assertEqual(applied.record["stay_length"], 5)
        self.assertEqual(who(applied), (2, 1, [6]))

    def test_a_person_and_a_night_in_one_message_are_both_read(self):
        applied = hear(
            "vai mais um amigo e ficamos mais uma noite",
            party(2),
            added=[("adult", None)],
            change={"nights_delta": 1},
        )

        self.assertEqual(who(applied)[0], 3)
        self.assertEqual(applied.record["stay_length"], 5)


class PartyOperationsTogetherTests(SimpleTestCase):
    def test_a_correction_and_an_addition_in_one_message(self):
        applied = hear(
            "o mais novo tem 5 e vai mais um amigo",
            party(2, 2, [4, 10]),
            correction={"to_age": 5, "which": "younger"},
            added=[("adult", None)],
        )

        self.assertEqual(who(applied), (3, 2, [5, 10]))

    def test_the_same_message_in_the_shape_the_model_returned(self):
        # The age as `child_ages` of one, and the friend reported with no kind of its own.
        applied = hear(
            "o mais novo tem 5 e vai mais um amigo",
            party(2, 2, [4, 10]),
            children=1,
            ages=[5],
            added=[("unsure", None)],
        )

        self.assertEqual(who(applied), (3, 2, [5, 10]))
        self.assertEqual(issues_of(applied), [])


class WordsThatCorrectNothingTests(SimpleTestCase):
    """A message the model found nothing in is only read as a correction when it plainly is one."""

    def test_an_age_in_a_message_about_somebody_else_changes_nothing(self):
        for message in (
            "o mais velho dos meus sobrinhos tem 15",
            "o mais novo tem 5 anos?",
            "o mais velho do grupo de amigos tem 40 anos e gosta muito de museus e de caminhar",
        ):
            with self.subTest(message=message):
                applied = hear(message, party(2, 2, [7, 12]))

                self.assertEqual(who(applied), (2, 2, [7, 12]))
                self.assertEqual(issues_of(applied), [])
                self.assertFalse(applied.details_changed)


# --- 4. the gate, the schema, the facts -------------------------------------------------------


class GateAndSchemaTests(SimpleTestCase):
    def test_messages_that_add_someone_reach_the_extraction(self):
        for message in (
            "vai mais um amigo",
            "se suma otro adulto",
            "another adult is joining us",
            "y mi amiga también viene",
            "my friend is coming too",
            "também vem a minha colega",
            "one more person is coming",
            # nouns the gate did not know are caught by "one more ... comes"
            "vai mais um menino",
            "vai mais uma garota",
            "mais um vem com a gente",
            "otra viene también",
            "another one is coming",
            "we are bringing one more",
        ):
            with self.subTest(message=message):
                self.assertTrue(has_trip_detail_cues(message))

    def test_naming_a_friend_or_a_partner_opens_it_whatever_the_verb(self):
        for message in (
            "se suma mi novia",
            "mi compañera de piso también",
            "vem o meu noivo",
            "my fiancée is joining",
            "o meu companheiro vai",
            "my roommate wants to come",
            "se une una prima",
        ):
            with self.subTest(message=message):
                self.assertTrue(has_trip_detail_cues(message))

    def test_children_nouns_that_name_no_trip_detail_by_themselves_open_it_too(self):
        for message in ("o menino vai", "a rapariga também", "my girl comes too", "chico y chica"):
            with self.subTest(message=message):
                self.assertTrue(has_trip_detail_cues(message))

    def test_ordinary_requests_for_something_else_still_do_not(self):
        for message in ("mostre outro destino", "show me another city", "quero ver outras opções"):
            with self.subTest(message=message):
                self.assertFalse(has_trip_detail_cues(message))

    def test_people_added_is_part_of_the_strict_schema_and_the_prompt(self):
        schema = TRIP_DETAILS_SCHEMA["schema"]
        item = schema["properties"]["people_added"]["items"]

        self.assertIn("people_added", schema["required"])
        self.assertEqual(item["properties"]["kind"]["enum"], ["adult", "child", "unsure"])
        self.assertEqual(item["required"], ["kind", "age"])
        self.assertIn("people_added", TRIP_DETAILS_SYSTEM_PROMPT)
        self.assertIn("children stays null", TRIP_DETAILS_SYSTEM_PROMPT)

    def test_validation_keeps_known_kinds_and_sane_ages_only(self):
        parsed = validate_components(
            {
                "people_added": [
                    {"kind": "adult", "age": None},
                    {"kind": "robot", "age": 3},
                    {"kind": "child", "age": 9},
                    {"kind": "unsure", "age": 400},
                    "nonsense",
                ]
            }
        )

        self.assertEqual(
            parsed["people_added"],
            [
                {"kind": "adult", "age": None},
                {"kind": "child", "age": 9},
                {"kind": "unsure", "age": None},
            ],
        )
        self.assertEqual(validate_components({"people_added": "nope"})["people_added"], [])
        self.assertEqual(validate_components({})["people_added"], [])

    def test_the_facts_say_an_age_is_never_a_date(self):
        facts = fact_block(
            TripTurn(trip=resolve(party(2, 1, [6]), TODAY), today=TODAY), always=True
        )

        self.assertIn("is an age: never a date, a check-out day or a number of nights", facts)

    def test_the_turn_marker_is_not_a_trip_detail(self):
        applied = hear("vai mais um amigo", party(2), turn_key=3, added=[("adult", None)])

        cleared = apply_components(applied.record, comps(cleared=["everything"]), TODAY, turn=4)

        self.assertEqual(applied.record["party_turn"], 3)
        self.assertIsNone(cleared.record)
        only_the_marker = apply_components(
            {**party(2), "party_turn": 2}, comps(cleared=["adults", "start", "stay"]), TODAY
        )
        self.assertIsNone(only_the_marker.record)


class TurnKeyTests(SimpleTestCase):
    def window(self, turns):
        history = []
        for n in range(turns):
            history += [
                {"role": "user", "content": f"message {n}"},
                {"role": "assistant", "content": f"reply {n}"},
            ]
        return history[-12:]  # the conversation memory keeps the last twelve messages

    def test_the_same_message_on_the_same_history_is_the_same_turn(self):
        self.assertEqual(
            _turn_index(self.window(3), "vai mais um amigo"),
            _turn_index(self.window(3), "vai mais um amigo"),
        )

    def test_another_message_is_another_turn(self):
        self.assertNotEqual(
            _turn_index(self.window(3), "vai mais um amigo"),
            _turn_index(self.window(3), "vai mais uma amiga"),
        )

    def test_turns_stay_apart_once_the_history_stops_growing(self):
        # Twelve messages are kept, so the count of the traveler's messages stops at six: the
        # same words, two turns apart, must still be two turns.
        early, later, latest = self.window(6), self.window(7), self.window(8)

        keys = {_turn_index(h, "vai mais um amigo") for h in (early, later, latest)}

        self.assertEqual(len(keys), 3)


# --- 5. through whole turns ---------------------------------------------------------------------


class PartyWholeTurnTests(_TripCase):
    """The Booking link, its caption and the reply's facts after each kind of update."""

    def tab(self, provider):
        return ViewSession(
            self.user, ai_provider=provider, climate_provider=self.climate, save=False
        )

    def ready(self, *later, adults=2, children=1, ages=(6,)):
        trip = {"adults": adults, **WHEN}
        if children:
            trip.update(children=children, child_ages=list(ages))
        provider = ScriptedProvider(
            [turn(spain(selected_destination_name="Barcelona")), stays(**trip), *later]
        )
        tab = self.tab(provider)
        tab.post("quero ir pra Barcelona")
        first = tab.post("hospedagem dia 5, 3 dias, somos 2 adultos e uma criança de 6 anos")
        return provider, tab, first

    BASE_QUERY = [
        ("ss", "Barcelona, Spain"),
        ("checkin", "2026-11-05"),
        ("checkout", "2026-11-08"),
    ]

    def test_another_child_with_an_age_moves_the_link_the_caption_and_the_facts_together(self):
        provider, tab, first = self.ready(
            turn(spain(), trip_details={"children": 1, "child_ages": [9]})
        )
        (before,) = first.cards

        added = tab.post("e mais uma criança de 9 anos")

        (card,) = added.cards
        self.assertEqual(
            query_of(card["accommodation_search_url"]),
            [
                *self.BASE_QUERY,
                ("group_adults", "2"),
                ("group_children", "2"),
                ("age", "6"),
                ("age", "9"),
            ],
        )
        self.assertEqual(
            card["accommodation_caption"],
            "Booking search: Barcelona · 5 Nov 2026 – 8 Nov 2026 (3 nights), month assumed"
            " · 2 adults · 2 children (age 6, 9)",
        )
        self.assertTrue(added.retire_stays)  # the button with one child is retired
        self.assertNotEqual(card["accommodation_search_url"], before["accommodation_search_url"])
        self.assertEqual(self.stored()["child_ages"], [6, 9])
        facts = self.prompt_of_last_reply(provider)
        self.assertIn("Children: 2, ages 6, 9 - included in the search.", facts)
        self.assertIn(
            "carries exactly: dates 2026-11-05 to 2026-11-08, 2 adults, 2 children", facts
        )

    def test_another_child_with_no_age_keeps_the_party_retires_the_button_and_asks(self):
        provider, tab, _ = self.ready(
            turn(
                spain(),
                trip_details={"children": 1, "people_added": [{"kind": "child", "age": None}]},
            ),
            turn(spain(), trip_details={"child_ages": [9]}),
        )

        waiting = tab.post("e mais uma criança")

        self.assertEqual(waiting.cards, [])
        self.assertTrue(waiting.retire_stays)
        self.assertEqual(
            (self.stored()["adults"], self.stored()["children"], self.stored()["child_ages"]),
            (2, 2, [6]),
        )
        facts = self.prompt_of_last_reply(provider)
        self.assertIn("the ages known so far are 6", facts)
        self.assertIn("There is NO Booking search action yet", facts)

        done = tab.post("tem 9 anos")

        (card,) = done.cards
        self.assertEqual(
            query_of(card["accommodation_search_url"])[3:],
            [("group_adults", "2"), ("group_children", "2"), ("age", "6"), ("age", "9")],
        )

    def test_another_adult_moves_the_link_and_the_caption(self):
        provider, tab, _ = self.ready(
            turn(spain(), trip_details={"people_added": [{"kind": "adult", "age": None}]})
        )

        added = tab.post("vai mais um amigo")

        (card,) = added.cards
        self.assertEqual(
            query_of(card["accommodation_search_url"])[3:],
            [("group_adults", "3"), ("group_children", "1"), ("age", "6")],
        )
        self.assertIn("3 adults · 1 child (age 6)", card["accommodation_caption"])
        self.assertTrue(added.retire_stays)
        self.assertIn("Adults: 3.", self.prompt_of_last_reply(provider))

    def test_a_relative_with_no_age_is_asked_about_and_not_counted(self):
        provider, tab, _ = self.ready(
            turn(spain(), trip_details={"people_added": [{"kind": "unsure", "age": None}]}),
            turn(spain(), trip_details={"people_added": [{"kind": "unsure", "age": 25}]}),
            adults=2,
            children=0,
        )

        waiting = tab.post("e meu primo vai também")

        self.assertEqual(waiting.cards, [])
        self.assertTrue(waiting.retire_stays)
        self.assertEqual(self.stored()["adults"], 2)  # no age assumed, so no adult counted
        self.assertIn("a child's age is missing", self.prompt_of_last_reply(provider))

        done = tab.post("ele tem 25 anos")

        (card,) = done.cards
        self.assertEqual(query_of(card["accommodation_search_url"])[3:], [("group_adults", "3")])

    def test_a_pointer_correction_in_the_shape_the_model_returns_moves_the_link(self):
        provider, tab, _ = self.ready(
            turn(
                spain(),
                trip_details={
                    "children": 1,
                    "child_ages": [5],
                    "age_correction": {"from_age": None, "to_age": 5, "which": None},
                },
            ),
            children=2,
            ages=(6, 9),
        )

        corrected = tab.post("o mais novo fez 5")

        (card,) = corrected.cards
        self.assertEqual(
            query_of(card["accommodation_search_url"])[3:],
            [("group_adults", "2"), ("group_children", "2"), ("age", "5"), ("age", "9")],
        )
        self.assertTrue(corrected.retire_stays)
        self.assertEqual(self.stored()["child_ages"], [5, 9])
        self.assertIn(
            "Children: 2, ages 5, 9 - included in the search.", self.prompt_of_last_reply(provider)
        )

    def test_a_child_corrected_into_an_adult_changes_the_link_consistently(self):
        provider, tab, _ = self.ready(
            turn(
                spain(),
                trip_details={
                    "children": 1,
                    "child_ages": [19],
                    "age_correction": {"from_age": None, "to_age": 19, "which": None},
                },
            ),
            children=2,
            ages=(6, 9),
        )

        corrected = tab.post("el mayor en realidad tiene 19")

        (card,) = corrected.cards
        self.assertEqual(
            query_of(card["accommodation_search_url"])[3:],
            [("group_adults", "3"), ("group_children", "1"), ("age", "6")],
        )
        self.assertIn("3 adults · 1 child (age 6)", card["accommodation_caption"])

    def test_a_correction_that_cannot_tell_which_child_changes_nothing_and_keeps_the_button(self):
        provider, tab, first = self.ready(
            turn(
                spain(),
                trip_details={
                    "children": 1,
                    "child_ages": [9],
                    "age_correction": {"from_age": None, "to_age": 9, "which": None},
                },
            ),
            children=2,
            ages=(7, 12),
        )

        asked = tab.post("ela tem 9 anos")

        self.assertEqual(asked.cards, [])
        self.assertFalse(asked.retire_stays)  # the link on the page is still right
        self.assertEqual(self.stored()["child_ages"], [7, 12])
        self.assertEqual(self.stored()["children"], 2)
        facts = self.prompt_of_last_reply(provider)
        self.assertIn("it is not clear which child", facts)
        self.assertIn("Children: 2, ages 7, 12 - included in the search.", facts)

    def test_an_addition_the_words_do_not_support_changes_nothing_and_is_not_claimed(self):
        provider, tab, _ = self.ready(
            turn(
                spain(),
                trip_details={
                    "children": 1,
                    "child_ages": [9],
                    "people_added": [{"kind": "child", "age": 9}],
                },
            ),
        )

        asked = tab.post("vamos levar a minha filha de 9 anos")

        self.assertEqual(asked.cards, [])
        self.assertFalse(asked.retire_stays)
        self.assertEqual(self.stored()["child_ages"], [6])
        facts = self.prompt_of_last_reply(provider)
        self.assertIn("Nothing was changed. Ask how many adults and how many children", facts)
        self.assertIn("Children: 1, ages 6 - included in the search.", facts)

    def test_someone_joining_before_anybody_is_going_asks_who_is_going(self):
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                turn(spain(), trip_details={"people_added": [{"kind": "adult", "age": None}]}),
            ]
        )
        tab = self.tab(provider)
        tab.post("quero ir pra Barcelona")

        asked = tab.post("vai mais um amigo")

        self.assertEqual(asked.cards, [])
        self.assertFalse(asked.retire_stays)
        self.assertIsNone(self.stored())
        self.assertIn("nothing to add them to", self.prompt_of_last_reply(provider))

    def test_a_retried_message_adds_the_person_once_and_the_next_one_adds_another(self):
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                stays(adults=2, **WHEN),
                *[plain(people_added=[{"kind": "adult", "age": None}])] * 3,
            ]
        )
        self.say(provider, "quero ir pra Barcelona")
        self.say(provider, "hospedagem dia 5, 3 dias, somos 2")
        before = list(cache.get(self.key))

        self.say(provider, "vai mais um amigo")
        self.assertEqual(self.stored()["adults"], 3)
        cache.set(self.key, before, 1800)  # the reply never got saved: the traveler sends it again
        self.say(provider, "vai mais um amigo")
        self.assertEqual(self.stored()["adults"], 3)
        self.say(provider, "vai mais um amigo")  # now it is a new message
        self.assertEqual(self.stored()["adults"], 4)

    def test_every_addition_counts_in_a_long_conversation(self):
        # Once the conversation memory is full the number of earlier messages stops growing.
        fillers = [turn(spain()) for _ in range(8)]
        provider = ScriptedProvider(
            [
                turn(spain(selected_destination_name="Barcelona")),
                stays(adults=2, **WHEN),
                *fillers,
                *[plain(people_added=[{"kind": "adult", "age": None}])] * 2,
            ]
        )
        self.say(provider, "quero ir pra Barcelona")
        self.say(provider, "hospedagem dia 5, 3 dias, somos 2")
        for n in range(8):
            self.say(provider, f"obrigado {n}")

        self.say(provider, "vai mais um amigo")
        self.say(provider, "vai mais um amigo")

        self.assertEqual(self.stored()["adults"], 4)
