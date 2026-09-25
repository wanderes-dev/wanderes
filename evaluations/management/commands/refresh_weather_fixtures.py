from django.core.management.base import BaseCommand

from evaluations.scenarios import load_corpus
from evaluations.weather_fixtures import (
    FIXTURE_PATH,
    FIXTURE_SCHEMA_VERSION,
    fixture_key,
    load_fixture_file,
    save_fixture_file,
    utcnow_iso,
)
from integrations.climate.base import ClimateProviderError
from integrations.climate.open_meteo import OpenMeteoClimateProvider
from travel.geography import countries_in_continent
from travel.models import Destination


def _candidate_destinations_for(deterministic_request: dict):
    """Mirrors recommendations.scoring.generate_recommendations's
    DB-level (pre-climate) filter chain - trip_type/max_cost_of_living/
    continent/country/excluded_slugs - so the fixture only needs to
    cover destinations a scenario could actually reach, not the whole
    384-destination catalog. Deliberately duplicated rather than
    importing a slice of generate_recommendations: that function has no
    "candidates only" seam to call into without changing production
    code, which this cycle is explicitly not allowed to do. If that
    filter chain ever changes, update this to match.
    """
    candidates = Destination.objects.exclude(
        slug__in=deterministic_request.get("excluded_slugs") or []
    )
    if deterministic_request.get("trip_type") is not None:
        candidates = candidates.filter(trip_type=deterministic_request["trip_type"])
    if deterministic_request.get("max_cost_of_living") is not None:
        candidates = candidates.filter(
            cost_of_living__lte=deterministic_request["max_cost_of_living"]
        )
    if deterministic_request.get("continent") is not None:
        candidates = candidates.filter(
            country__in=countries_in_continent(deterministic_request["continent"])
        )
    if deterministic_request.get("country") is not None:
        candidates = candidates.filter(country__icontains=deterministic_request["country"])
    return candidates


def compute_needed_keys(scenarios) -> dict[str, tuple[float, float, int]]:
    """Returns {fixture_key: (latitude, longitude, month)} for every
    (destination, month) pair the corpus's deterministic_request-bearing
    scenarios could touch."""
    needed = {}
    for scenario in scenarios:
        if scenario.deterministic_request is None:
            continue
        month = scenario.deterministic_request["month"]
        for destination in _candidate_destinations_for(scenario.deterministic_request):
            key = fixture_key(float(destination.latitude), float(destination.longitude), month)
            needed[key] = (float(destination.latitude), float(destination.longitude), month)
    return needed


class Command(BaseCommand):
    help = (
        "Captures real MonthlyClimateSummary data from Open-Meteo into the "
        "version-controlled evaluation fixture (evaluations/fixtures/weather.json). "
        "Resumable - never re-fetches an entry already in the fixture. Never "
        "fabricates a value: a request that fails is left uncaptured, not guessed. "
        "Requires live Open-Meteo access - this is the one evaluation command "
        "that's expected to touch the network."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Only report how many (destination, month) pairs are "
                "needed/missing - no requests."
            ),
        )

    def handle(self, *args, **options):
        scenarios = load_corpus()
        needed = compute_needed_keys(scenarios)
        document = load_fixture_file()
        if document.get("schema_version") != FIXTURE_SCHEMA_VERSION:
            self.stdout.write(
                self.style.WARNING(
                    f"Fixture schema_version {document.get('schema_version')!r} != "
                    f"current {FIXTURE_SCHEMA_VERSION!r} - proceeding, but consider "
                    "regenerating from scratch."
                )
            )
        existing_entries = document.setdefault("entries", {})
        missing = {k: v for k, v in needed.items() if k not in existing_entries}

        self.stdout.write(
            f"{len(needed)} (destination, month) pair(s) needed by the corpus, "
            f"{len(needed) - len(missing)} already captured, {len(missing)} missing."
        )
        if options["dry_run"] or not missing:
            if not missing and needed:
                self.stdout.write(self.style.SUCCESS("Fixture already covers everything needed."))
            return

        provider = OpenMeteoClimateProvider()
        captured, failed = 0, 0
        for i, (key, (lat, lon, month)) in enumerate(sorted(missing.items()), start=1):
            try:
                summary = provider.get_monthly_climate(latitude=lat, longitude=lon, month=month)
            except ClimateProviderError as exc:
                failed += 1
                self.stdout.write(f"  [{i}/{len(missing)}] FAILED {key}: {exc}")
                # A real daily-quota exhaustion (confirmed 2026-09-25: a raw
                # HTTP call to the same endpoint returned 429 "Daily API
                # request limit exceeded. Please try again tomorrow.")
                # means every subsequent attempt will fail identically -
                # stop early rather than hammering a rate-limited free API
                # for no benefit. A handful of early, consecutive failures
                # is treated as this same signal, since the production
                # adapter's ClimateProviderError doesn't preserve the
                # underlying HTTP status to check more precisely without
                # touching production code (out of scope this cycle).
                if failed >= 3 and captured == 0:
                    self.stdout.write(
                        self.style.WARNING(
                            f"{failed} consecutive failures with zero successes - likely a "
                            "provider-wide outage or exhausted quota, not per-request bad luck. "
                            "Stopping early rather than continuing to hit the API. Re-run this "
                            "command later to resume - already-captured entries are preserved."
                        )
                    )
                    break
                continue
            existing_entries[key] = {
                "avg_high_c": summary.avg_high_c,
                "avg_low_c": summary.avg_low_c,
                "total_precipitation_mm": summary.total_precipitation_mm,
                "source_year": summary.year,
                "captured_at": utcnow_iso(),
            }
            captured += 1
            self.stdout.write(f"  [{i}/{len(missing)}] captured {key}")

        document["schema_version"] = FIXTURE_SCHEMA_VERSION
        document.setdefault("provenance", []).append(
            {
                "captured_at": utcnow_iso(),
                "captured_by": "python manage.py refresh_weather_fixtures",
                "source": "https://archive-api.open-meteo.com/v1/archive",
                "entries_added": captured,
                "entries_failed": failed,
            }
        )
        save_fixture_file(document)

        style = self.style.SUCCESS if captured else self.style.WARNING
        self.stdout.write(
            style(f"Captured {captured} new entries, {failed} failed. Fixture: {FIXTURE_PATH}")
        )
