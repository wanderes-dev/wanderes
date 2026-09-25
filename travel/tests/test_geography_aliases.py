from django.test import SimpleTestCase

from travel.geography_aliases import canonicalize_country_name


class CanonicalizeCountryNameTests(SimpleTestCase):
    def test_english_variants_resolve_to_usa(self):
        for alias in [
            "United States",
            "United States of America",
            "US",
            "U.S.",
            "U.S.A.",
            "America",
        ]:
            with self.subTest(alias=alias):
                self.assertEqual(canonicalize_country_name(alias), "USA")

    def test_portuguese_variants_resolve_to_usa(self):
        self.assertEqual(canonicalize_country_name("Estados Unidos"), "USA")
        self.assertEqual(canonicalize_country_name("EUA"), "USA")

    def test_portuguese_thailand_resolves(self):
        self.assertEqual(canonicalize_country_name("Tailândia"), "Thailand")

    def test_is_case_insensitive(self):
        self.assertEqual(canonicalize_country_name("united states"), "USA")
        self.assertEqual(canonicalize_country_name("TAILÂNDIA"), "Thailand")

    def test_strips_whitespace(self):
        self.assertEqual(canonicalize_country_name("  United States  "), "USA")

    def test_already_canonical_value_passes_through_unchanged(self):
        self.assertEqual(canonicalize_country_name("USA"), "USA")
        self.assertEqual(canonicalize_country_name("Thailand"), "Thailand")

    def test_unrecognized_name_passes_through_unchanged_not_guessed(self):
        # Never fuzzy-matched - an unmapped name is handed back as-is so
        # the normal is_known_country() check can accept or reject it.
        self.assertEqual(canonicalize_country_name("Wakanda"), "Wakanda")

    def test_a_real_city_name_passes_through_unchanged(self):
        # This table only ever rewrites country-level aliases - a city
        # name must never be silently altered.
        self.assertEqual(canonicalize_country_name("Marrakech"), "Marrakech")

    def test_empty_or_none_input_returns_empty_string(self):
        self.assertEqual(canonicalize_country_name(""), "")
        self.assertEqual(canonicalize_country_name(None), "")

    def test_a_sample_of_other_portuguese_translations_resolve(self):
        cases = {
            "Alemanha": "Germany",
            "Espanha": "Spain",
            "Japão": "Japan",
            "Grécia": "Greece",
            "México": "Mexico",
            "Coreia do Sul": "South Korea",
            "Reino Unido": "United Kingdom",
            "Marrocos": "Morocco",
        }
        for alias, expected in cases.items():
            with self.subTest(alias=alias):
                self.assertEqual(canonicalize_country_name(alias), expected)
