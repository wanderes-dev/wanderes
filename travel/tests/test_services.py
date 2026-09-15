from django.test import TestCase

from travel.models import CountryEntryRequirement, Destination
from travel.services import (
    find_destination_slugs_by_name,
    get_entry_requirements,
    is_known_country,
    resolve_country_name,
)


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


class ResolveCountryNameTests(TestCase):
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

    def test_resolves_a_destination_name_to_its_country(self):
        self.assertEqual(resolve_country_name("Lisbon"), "Portugal")

    def test_resolves_a_country_name_that_matches_a_destination(self):
        self.assertEqual(resolve_country_name("Portugal"), "Portugal")

    def test_is_case_insensitive(self):
        self.assertEqual(resolve_country_name("lisbon"), "Portugal")

    def test_falls_back_to_the_raw_input_when_nothing_matches(self):
        self.assertEqual(resolve_country_name("Nowhereland"), "Nowhereland")

    def test_empty_input_returns_none(self):
        self.assertIsNone(resolve_country_name(""))
        self.assertIsNone(resolve_country_name("   "))


class IsKnownCountryTests(TestCase):
    """ai.orchestration._validate_intent uses this to catch a multi-country
    region ("Scandinavia") the extraction prompt captured into `country`
    as if it were one real country - see that function's comment."""

    def setUp(self):
        Destination.objects.create(
            slug="oslo-no",
            name="Oslo",
            country="Norway",
            latitude=59.91,
            longitude=10.75,
            trip_type="city",
            cost_of_living=4,
            best_season="Jun-Aug",
            worst_season="Dec-Feb",
            short_description="A fjord-side capital.",
            points_of_interest=[],
        )

    def test_true_for_a_real_country_in_the_catalog(self):
        self.assertTrue(is_known_country("Norway"))

    def test_is_case_insensitive(self):
        self.assertTrue(is_known_country("norway"))

    def test_strips_whitespace(self):
        self.assertTrue(is_known_country("  Norway  "))

    def test_false_for_a_multi_country_region_name(self):
        self.assertFalse(is_known_country("Scandinavia"))

    def test_false_for_an_unrelated_string(self):
        self.assertFalse(is_known_country("Nowhereland"))
