import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from travel.models import CountryEntryRequirement

# Lives inside the travel app itself, same reasoning as
# load_destinations.py's DEFAULT_DATASET_PATH - real application data, not
# developer documentation, so it isn't silently excluded from the Docker
# image by .dockerignore.
DEFAULT_DATASET_PATH = (
    settings.BASE_DIR / "travel" / "data" / "country_entry_requirements.json"
)


class Command(BaseCommand):
    help = (
        "Load (or refresh) the country entry-requirement (visa/vaccine/insurance) dataset. "
        "See travel/data/country_entry_requirements.json's $schema_note for this data's "
        "coverage and confidence limits before relying on it."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            default=str(DEFAULT_DATASET_PATH),
            help="Path to the country entry-requirements JSON file.",
        )

    def handle(self, *args, **options):
        path = Path(options["path"])
        data = json.loads(path.read_text(encoding="utf-8"))

        created_count = 0
        updated_count = 0
        for entry in data["countries"]:
            _, created = CountryEntryRequirement.objects.update_or_create(
                country=entry["country"],
                defaults={
                    "visa_required_nationalities": entry.get("visa_required_nationalities", []),
                    "visa_notes": entry.get("visa_notes", ""),
                    "vaccine_requirements": entry.get("vaccine_requirements", []),
                    "insurance_required": entry.get("insurance_required", False),
                    "insurance_notes": entry.get("insurance_notes", ""),
                    "other_requirements": entry.get("other_requirements", []),
                },
            )
            if created:
                created_count += 1
            else:
                updated_count += 1

        message = (
            f"Loaded {created_count} new, updated {updated_count} existing "
            "country entry requirements."
        )
        self.stdout.write(self.style.SUCCESS(message))
