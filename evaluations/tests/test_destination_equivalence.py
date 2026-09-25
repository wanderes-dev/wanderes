from django.test import SimpleTestCase

from evaluations.destination_equivalence import (
    mentions_destination,
    normalize_for_comparison,
)


class NormalizeForComparisonTests(SimpleTestCase):
    def test_diacritic_variant_matches_plain_ascii(self):
        # Cycle 1.5's original evidentiary trigger: STR-004 scored Brasov
        # (the catalog's plain-ASCII name) as the deterministic #1, but
        # the AI's Portuguese reply correctly wrote "Brașov" with the
        # real Romanian diacritic - a textual encoding difference, not a
        # different destination.
        self.assertEqual(normalize_for_comparison("Brașov"), normalize_for_comparison("Brasov"))

    def test_case_difference_matches(self):
        self.assertEqual(normalize_for_comparison("PARIS"), normalize_for_comparison("paris"))

    def test_genuinely_different_words_do_not_match(self):
        # Rome vs Roma differ by more than accents - normalization alone
        # must NOT bridge this; it needs the explicit alias table.
        self.assertNotEqual(normalize_for_comparison("Rome"), normalize_for_comparison("Roma"))


class MentionsDestinationTests(SimpleTestCase):
    def test_exact_canonical_name_matches(self):
        self.assertTrue(
            mentions_destination(
                "I recommend Paris for your trip.", slug="paris-fr", name="Paris", country="France"
            )
        )

    def test_case_difference_matches(self):
        self.assertTrue(
            mentions_destination(
                "voce vai adorar paris!", slug="paris-fr", name="Paris", country="France"
            )
        )

    def test_diacritic_variant_matches_via_normalization(self):
        self.assertTrue(
            mentions_destination(
                "Recomendo Brașov para sua viagem.",
                slug="brasov-ro",
                name="Brasov",
                country="Romania",
            )
        )

    def test_portuguese_exonym_matches_via_explicit_alias(self):
        self.assertTrue(
            mentions_destination(
                "Roma é perfeita para você.", slug="roma-it", name="Rome", country="Italy"
            )
        )

    def test_tokyo_portuguese_exonym_matches(self):
        self.assertTrue(
            mentions_destination(
                "Tóquio combina com seu perfil.", slug="toquio-jp", name="Tokyo", country="Japan"
            )
        )

    def test_country_name_alone_is_accepted(self):
        self.assertTrue(
            mentions_destination(
                "That place in France is incredible.",
                slug="paris-fr",
                name="Paris",
                country="France",
            )
        )

    def test_unrelated_destination_does_not_match(self):
        # The traveler's own stated requirement: "Paris must not
        # accidentally match an unrelated similarly spelled destination."
        # Neither the name, the country, nor any known alias for Rome
        # appears in a reply about Paris.
        self.assertFalse(
            mentions_destination(
                "Recomendo fortemente Paris para sua viagem romantica.",
                slug="roma-it",
                name="Rome",
                country="Italy",
            )
        )

    def test_slug_with_no_alias_entry_still_works_on_exact_name(self):
        self.assertTrue(
            mentions_destination(
                "Lima é uma ótima escolha.", slug="lima-pe", name="Lima", country="Peru"
            )
        )

    def test_slug_with_no_alias_entry_and_no_mention_fails(self):
        self.assertFalse(
            mentions_destination(
                "Nao encontrei nada parecido.", slug="lima-pe", name="Lima", country="Peru"
            )
        )

    def test_alias_does_not_match_as_a_substring_of_an_unrelated_word(self):
        # The exact false-positive this module's word-boundary matching
        # exists to prevent: "roma" (the alias for Rome) is a literal
        # substring of the unrelated Portuguese word "romantica"
        # ("romantic"). A naive `in` check would wrongly credit a reply
        # about Paris with mentioning Rome.
        self.assertFalse(
            mentions_destination(
                "Recomendo fortemente Paris para sua viagem romantica.",
                slug="roma-it",
                name="Rome",
                country="Italy",
            )
        )

    def test_alias_still_matches_as_a_standalone_word(self):
        self.assertTrue(
            mentions_destination(
                "Roma e uma cidade incrivel para uma viagem romantica.",
                slug="roma-it",
                name="Rome",
                country="Italy",
            )
        )
