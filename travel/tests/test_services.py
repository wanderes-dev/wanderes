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

    def test_a_portuguese_country_alias_resolves_before_matching(self):
        # Evaluation Improvement Cycle 1, Fix B (2026-09-25 baseline,
        # ADV-007): "excluir a Tailândia" never matched the catalog's
        # "Thailand" - a literal substring match against untranslated
        # Portuguese, since no canonicalization step existed at all.
        bangkok = Destination.objects.create(
            slug="bangkok-th",
            name="Bangkok",
            country="Thailand",
            latitude=13.75,
            longitude=100.5,
            trip_type="city",
            cost_of_living=2,
            best_season="Nov-Feb",
            worst_season="Apr-May",
            short_description="A vibrant riverside capital.",
            points_of_interest=[],
        )

        slugs = find_destination_slugs_by_name(["Tailândia"])

        self.assertEqual(slugs, frozenset({bangkok.slug}))

    def test_an_actual_city_name_is_unaffected_by_alias_canonicalization(self):
        # canonicalize_country_name() only ever rewrites a recognized
        # country alias - a real city name like "Marrakech" must still
        # match normally, not get silently altered.
        slugs = find_destination_slugs_by_name(["Marrakech"])

        self.assertEqual(slugs, frozenset({"marrakech-ma"}))


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


class IsKnownCountryAliasTests(TestCase):
    """Evaluation Improvement Cycle 1, Fix B (2026-09-25 baseline,
    STR-032): the AI reasonably extracts country='United States', but
    this catalog stores 'USA' - is_known_country('United States') used
    to return False even though the US is very much in the catalog with
    real scoring data, silently routing a legitimate US request into
    the general-knowledge fallback."""

    def setUp(self):
        Destination.objects.create(
            slug="nova-york-us",
            name="New York",
            country="USA",
            latitude=40.71,
            longitude=-74.01,
            trip_type="city",
            cost_of_living=5,
            best_season="Apr-Jun",
            worst_season="Jan-Feb",
            short_description="A dense, iconic metropolis.",
            points_of_interest=[],
        )

    def test_united_states_resolves_to_the_catalogs_usa(self):
        self.assertTrue(is_known_country("United States"))

    def test_us_abbreviation_resolves(self):
        self.assertTrue(is_known_country("US"))

    def test_portuguese_estados_unidos_resolves(self):
        self.assertTrue(is_known_country("Estados Unidos"))

    def test_portuguese_eua_resolves(self):
        self.assertTrue(is_known_country("EUA"))

    def test_the_catalogs_own_value_still_matches_directly(self):
        self.assertTrue(is_known_country("USA"))

    def test_unrecognized_alias_still_returns_false(self):
        # Not a fuzzy match - an alias not in the explicit table is
        # judged on its own, same as before this fix.
        self.assertFalse(is_known_country("The States"))
