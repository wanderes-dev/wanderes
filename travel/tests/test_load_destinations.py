from django.core.management import call_command
from django.test import TestCase

from travel.management.commands.load_destinations import DEFAULT_DATASET_PATH
from travel.models import Destination


class LoadDestinationsCommandTests(TestCase):
    def test_default_dataset_path_exists(self):
        # Regression test: this file previously lived under documentation/,
        # which .dockerignore excludes from the built image - it only ever
        # worked locally because docker-compose.yml bind-mounts the whole
        # project directory, masking the gap until a real deploy (no bind
        # mount) hit it with a bare FileNotFoundError. Now lives under
        # travel/data/ - real application data, not documentation.
        self.assertTrue(DEFAULT_DATASET_PATH.exists())

    def test_load_destinations_with_default_path_creates_destinations(self):
        call_command("load_destinations")

        self.assertTrue(Destination.objects.exists())
