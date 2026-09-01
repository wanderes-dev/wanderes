from django.db import IntegrityError, transaction
from django.test import TestCase

from travel.models import CountryEntryRequirement, Destination


class DestinationTests(TestCase):
    def test_create_destination(self):
        destination = Destination.objects.create(
            slug="lisbon-pt",
            name="Lisbon",
            country="Portugal",
            latitude="38.72000",
            longitude="-9.14000",
            trip_type="city",
            cost_of_living=3,
            best_season="Mar-Oct",
            worst_season="Dec-Feb",
            short_description="A hilly coastal capital.",
            points_of_interest=["Belem Tower", "Alfama"],
        )

        self.assertEqual(str(destination), "Lisbon, Portugal")
        self.assertEqual(destination.points_of_interest, ["Belem Tower", "Alfama"])


class CountryEntryRequirementTests(TestCase):
    def test_create_country_entry_requirement(self):
        requirement = CountryEntryRequirement.objects.create(
            country="Testland",
            visa_required_nationalities=["Brazil", "India"],
            visa_notes="Visa-free for most of Europe.",
            vaccine_requirements=["Yellow Fever - if arriving from an endemic country"],
            insurance_required=True,
            insurance_notes="Minimum coverage required.",
            other_requirements=["Passport valid 6 months beyond stay"],
        )

        self.assertEqual(str(requirement), "Entry requirements for Testland")
        self.assertEqual(requirement.visa_required_nationalities, ["Brazil", "India"])
        self.assertTrue(requirement.insurance_required)

    def test_country_is_unique(self):
        CountryEntryRequirement.objects.create(country="Testland")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CountryEntryRequirement.objects.create(country="Testland")
