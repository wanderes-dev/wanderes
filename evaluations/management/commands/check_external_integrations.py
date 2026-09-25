import time

from django.core.management.base import BaseCommand, CommandError

from integrations.climate import get_climate_provider
from integrations.climate.base import ClimateProviderError

# A real, well-known coordinate/month - not corpus data, just something
# stable to probe with. Any real destination would do.
_PROBE_LATITUDE = 48.8566  # Paris
_PROBE_LONGITUDE = 2.3522
_PROBE_MONTH = 6


class Command(BaseCommand):
    help = (
        "Checks whether a real third-party integration is currently reachable - "
        "answers 'is the live provider up right now', never 'is recommendation "
        "quality good'. Makes a real network call and is never run by pytest/CI "
        "or by evaluate_recommendations's default (fixture-backed) mode - opt-in "
        "only, and it can fail because of the third party's own availability, "
        "not because of anything in this codebase."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--weather",
            action="store_true",
            help="Check the live Open-Meteo climate integration specifically.",
        )

    def handle(self, *args, **options):
        if not options["weather"]:
            raise CommandError(
                "Specify which integration to check, e.g. --weather. "
                "(Only one integration exists to check today; the flag is "
                "required anyway so this command's purpose is explicit at "
                "the call site, not implicit in a bare default.)"
            )
        self.stdout.write(
            self.style.WARNING(
                "This makes a REAL request to the live Open-Meteo API - it consumes "
                "that provider's quota and can fail due to their availability, not "
                "ours."
            )
        )
        self._check_weather()

    def _check_weather(self):
        provider = get_climate_provider()
        started = time.perf_counter()
        try:
            summary = provider.get_monthly_climate(
                latitude=_PROBE_LATITUDE, longitude=_PROBE_LONGITUDE, month=_PROBE_MONTH
            )
        except ClimateProviderError as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000
            self.stdout.write(
                self.style.ERROR(f"UNREACHABLE ({elapsed_ms:.0f}ms): {exc}")
            )
            return
        elapsed_ms = (time.perf_counter() - started) * 1000
        self.stdout.write(
            self.style.SUCCESS(
                f"OK ({elapsed_ms:.0f}ms): avg_high_c={summary.avg_high_c} "
                f"avg_low_c={summary.avg_low_c} year={summary.year}"
            )
        )
