import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from travel.models import Destination

DEFAULT_DATASET_PATH = settings.BASE_DIR / "documentation" / "data" / "curated_destinations.json"


class Command(BaseCommand):
    help = "Load (or refresh) the curated destination dataset approved in Phase 3."

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            default=str(DEFAULT_DATASET_PATH),
            help="Path to the curated destinations JSON file.",
        )

    def handle(self, *args, **options):
        path = Path(options["path"])
        data = json.loads(path.read_text(encoding="utf-8"))

        created_count = 0
        updated_count = 0
        for entry in data["destinations"]:
            _, created = Destination.objects.update_or_create(
                slug=entry["slug"],
                defaults={
                    "name": entry["name"],
                    "country": entry["country"],
                    "latitude": entry["coordinates"]["lat"],
                    "longitude": entry["coordinates"]["lon"],
                    "trip_type": self._normalize_trip_type(entry["trip_type"]),
                    "cost_of_living": entry["cost_of_living"],
                    "best_season": entry["best_season"],
                    "worst_season": entry["worst_season"],
                    "short_description": entry["short_description"],
                    "points_of_interest": entry["points_of_interest"],
                },
            )
            if created:
                created_count += 1
            else:
                updated_count += 1

        message = f"Loaded {created_count} new, updated {updated_count} existing destinations."
        self.stdout.write(self.style.SUCCESS(message))

    @staticmethod
    def _normalize_trip_type(raw_trip_type):
        # The dataset's trip_type is free-form Portuguese (e.g. "Praia/natureza");
        # the model's trip_type is a single English choice. Map on the first
        # segment, defaulting to "city" if nothing matches.
        first_segment = raw_trip_type.split("/")[0].strip().lower()
        mapping = {
            "praia": "beach",
            "cidade": "city",
            "natureza": "nature",
            "cultura": "culture",
            "aventura": "nature",
        }
        return mapping.get(first_segment, "city")
