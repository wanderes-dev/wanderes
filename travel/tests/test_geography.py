from django.test import TestCase

from travel.geography import COUNTRIES_BY_CONTINENT, countries_in_continent
from travel.models import Destination


class ContinentClassificationCoversEveryCuratedCountryTests(TestCase):
    """2026-09-04, real production bug: a "Eurotrip" request's
    recommendation cards included Bali, Marrakech, Chiang Mai, Hoi An,
    and Ayutthaya alongside the genuinely European options, because
    nothing classified Destination.country by continent at all.

    A country present in the curated catalog but missing from every
    continent set wouldn't raise an error - countries_in_continent()
    would just never match it, silently excluding every one of its
    destinations from that continent's results instead of including
    them or failing loudly. This test is the actual safety net: it must
    be updated whenever travel/data/curated_destinations.json introduces
    a country not already classified in travel/geography.py."""

    def test_every_destination_country_is_classified_in_exactly_one_continent(self):
        db_countries = set(Destination.objects.values_list("country", flat=True).distinct())
        classified_countries = set()
        seen_in = {}
        for continent, countries in COUNTRIES_BY_CONTINENT.items():
            for country in countries:
                self.assertNotIn(
                    country,
                    seen_in,
                    f"{country!r} is classified in both {seen_in.get(country)!r} and "
                    f"{continent!r} - every country must belong to exactly one continent.",
                )
                seen_in[country] = continent
            classified_countries |= countries

        missing = db_countries - classified_countries
        self.assertEqual(
            missing,
            set(),
            f"These countries exist in the curated catalog but aren't classified in "
            f"travel/geography.py: {sorted(missing)}",
        )


class CountriesInContinentTests(TestCase):
    def test_known_continent_returns_its_countries(self):
        self.assertIn("Portugal", countries_in_continent("europe"))
        self.assertIn("Japão", countries_in_continent("asia"))

    def test_a_country_is_never_in_two_different_continents_result(self):
        self.assertNotIn("Portugal", countries_in_continent("asia"))
        self.assertNotIn("Japão", countries_in_continent("europe"))

    def test_unknown_continent_code_returns_empty_set_rather_than_raising(self):
        self.assertEqual(countries_in_continent("not-a-real-continent"), frozenset())
