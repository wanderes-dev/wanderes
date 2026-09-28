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
from travel.services import find_destination_slugs_by_name


def _candidate_destinations_for(request: dict):
    """Mirrors recommendations.scoring.generate_recommendations's
    DB-level (pre-climate) filter chain - trip_type/max_cost_of_living/
    continent/country/excluded_slugs - so the fixture only needs to
    cover destinations a scenario could actually reach, not the whole
    384-destination catalog. Deliberately duplicated rather than
    importing a slice of generate_recommendations: that function has no
    "candidates only" seam to call into without changing production
    code. If that filter chain ever changes, update this to match.
    """
    candidates = Destination.objects.exclude(slug__in=request.get("excluded_slugs") or [])
    if request.get("trip_type") is not None:
        candidates = candidates.filter(trip_type=request["trip_type"])
    if request.get("max_cost_of_living") is not None:
        candidates = candidates.filter(cost_of_living__lte=request["max_cost_of_living"])
    if request.get("continent") is not None:
        candidates = candidates.filter(country__in=countries_in_continent(request["continent"]))
    if request.get("country") is not None:
        candidates = candidates.filter(country__icontains=request["country"])
    return candidates


def _effective_base_request(scenario) -> dict | None:
    """A deterministic_request-shaped dict to target fixture capture
    around, even for a scenario that has no deterministic_request of its
    own (a multi-turn or mind-changed scenario whose real request only
    exists inside conversation history/context). Falls back to whatever
    expected_intent fields the scenario does assert - an omitted field
    reads as unconstrained, same as it would from a bare
    deterministic_request. None for a scenario that never reaches
    scoring at all (its expected_flow isn't "recommendation"), since
    nothing needs capturing for those regardless of the AI's own
    classification on a given run.
    """
    if scenario.deterministic_request is not None:
        return scenario.deterministic_request
    if scenario.expected_flow != "recommendation":
        return None
    intent = scenario.expected_intent
    excluded_names = intent.get("excluded_place_names") or []
    return {
        "month": intent.get("month"),
        "trip_type": intent.get("trip_type"),
        "max_cost_of_living": intent.get("max_cost_of_living"),
        "continent": intent.get("continent"),
        "country": intent.get("country"),
        "excluded_slugs": list(find_destination_slugs_by_name(excluded_names)),
    }


def _relaxed_requests(base_request: dict) -> list[dict]:
    """A scenario's own deterministic_request/expected_intent records
    what a *correct* extraction should produce - but a real, full-
    pipeline run's live extraction is what actually decides which
    destinations get scored, and it can land one tier off on a numeric
    field (a "mid-range" budget read as 3 instead of 4) or skip a soft
    category the scenario's own ground truth asserts (a destination
    tagged "culture" reached even though the scenario names trip_type
    "city"). trip_type and max_cost_of_living are exactly the two
    fields this codebase has repeatedly seen drift this way; continent/
    country aren't included here since they're a much more binary match
    and relaxing them would multiply the needed-key count for little
    real benefit. Returns the exact request alone when there's nothing
    to relax.
    """
    has_trip_type = base_request.get("trip_type") is not None
    has_budget = base_request.get("max_cost_of_living") is not None
    variants = [base_request]
    if has_trip_type or has_budget:
        variants.append({**base_request, "trip_type": None, "max_cost_of_living": None})
    return variants


def _months_to_check(request: dict) -> list[int]:
    # A scenario whose effective month is never actually asserted (a
    # mind-changed or context-only turn where the app would fall back to
    # "the current month") can't be pinned to one specific month ahead of
    # time - cover every month it could conceivably land on instead.
    month = request.get("month")
    return [month] if month is not None else list(range(1, 13))


def compute_needed_keys(scenarios) -> dict[str, tuple[float, float, int]]:
    """Returns {fixture_key: (latitude, longitude, month)} for every
    (destination, month) pair a full-pipeline evaluation run could
    plausibly reach for scoring - not just the narrow set each
    scenario's own ground truth names literally, since real extraction
    doesn't always land exactly on that ground truth (see
    _relaxed_requests/_effective_base_request)."""
    needed = {}
    for scenario in scenarios:
        base_request = _effective_base_request(scenario)
        if base_request is None:
            continue
        months = _months_to_check(base_request)
        destinations = set()
        for request in _relaxed_requests(base_request):
            destinations.update(_candidate_destinations_for(request))
        for destination in destinations:
            for month in months:
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
