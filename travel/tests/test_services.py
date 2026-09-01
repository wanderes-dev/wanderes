from django.test import TestCase

from travel.models import CountryEntryRequirement, Destination
from travel.services import find_destination_slugs_by_name, get_entry_requirements


class FindDestinationSlugsByNameTests(TestCase):
    def setUp(self):
        self.lisbon = Destination.objects.create(
            slug="lisbon-pt",
            name="Lisbon",
            country="Portugal",
            latitude=38.72,
            longitude=-9.14,
            trip_type="city",
            cost_of_living=3,
            best_season="Mar-Oct",
            worst_season="Dec-Feb",
            short_description="A hilly coastal capital.",
            points_of_interest=[],
        )
        self.marrakech = Destination.objects.create(
            slug="marrakech-ma",
            name="Marrakech",
            country="Morocco",
            latitude=31.63,
            longitude=-7.99,
            trip_type="culture",
            cost_of_living=1,
            best_season="Mar-May",
            worst_season="Jul-Aug",
            short_description="A walled city.",
            points_of_interest=[],
        )

    def test_matches_by_name(self):
        slugs = find_destination_slugs_by_name(["Marrakech"])

        self.assertEqual(slugs, frozenset({"marrakech-ma"}))

    def test_matches_by_country(self):
        slugs = find_destination_slugs_by_name(["Morocco"])

        self.assertEqual(slugs, frozenset({"marrakech-ma"}))

    def test_is_case_insensitive(self):
        slugs = find_destination_slugs_by_name(["marrakech"])

        self.assertEqual(slugs, frozenset({"marrakech-ma"}))

    def test_no_match_returns_empty(self):
        slugs = find_destination_slugs_by_name(["Nowhereland"])

        self.assertEqual(slugs, frozenset())

    def test_empty_list_returns_empty(self):
        self.assertEqual(find_destination_slugs_by_name([]), frozenset())

    def test_multiple_terms_combine(self):
        slugs = find_destination_slugs_by_name(["Marrakech", "Portugal"])

        self.assertEqual(slugs, frozenset({"marrakech-ma", "lisbon-pt"}))


class GetEntryRequirementsTests(TestCase):
    def setUp(self):
        self.requirement = CountryEntryRequirement.objects.create(
            country="Testland",
            visa_required_nationalities=["Brazil"],
        )

    def test_matches_by_exact_country_name(self):
        self.assertEqual(get_entry_requirements("Testland"), self.requirement)

    def test_is_case_insensitive(self):
        self.assertEqual(get_entry_requirements("testland"), self.requirement)

    def test_strips_whitespace(self):
        self.assertEqual(get_entry_requirements("  Testland  "), self.requirement)

    def test_no_match_returns_none(self):
        self.assertIsNone(get_entry_requirements("Nowhereland"))

    def test_empty_name_returns_none(self):
        self.assertIsNone(get_entry_requirements(""))
