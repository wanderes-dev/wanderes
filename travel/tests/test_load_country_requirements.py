from django.core.management import call_command
from django.test import TestCase

from travel.management.commands.load_country_requirements import DEFAULT_DATASET_PATH
from travel.models import CountryEntryRequirement


class LoadCountryRequirementsCommandTests(TestCase):
    def test_default_dataset_path_exists(self):
        self.assertTrue(DEFAULT_DATASET_PATH.exists())

    def test_load_with_default_path_creates_entries(self):
        call_command("load_country_requirements")

        self.assertTrue(CountryEntryRequirement.objects.exists())

    def test_rerunning_updates_rather_than_duplicates(self):
        call_command("load_country_requirements")
        first_count = CountryEntryRequirement.objects.count()

        call_command("load_country_requirements")

        self.assertEqual(CountryEntryRequirement.objects.count(), first_count)
