from django.core.management import call_command
from django.test import TestCase

from travel.management.commands.load_destinations import DEFAULT_DATASET_PATH
from travel.models import Destination


class LoadDestinationsCommandTests(TestCase):
    def test_default_dataset_path_exists(self):
        # Regression test: this used to live under documentation/, which
        # .dockerignore excludes from the image - worked locally only
        # because docker-compose bind-mounts the whole project, so it took
        # a real deploy to surface the FileNotFoundError. Now lives under
        # travel/data/.
        self.assertTrue(DEFAULT_DATASET_PATH.exists())

    def test_load_destinations_with_default_path_creates_destinations(self):
        call_command("load_destinations")

        self.assertTrue(Destination.objects.exists())
