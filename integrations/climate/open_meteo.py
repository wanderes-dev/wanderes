import calendar
from datetime import date

import requests
from django.core.cache import cache

from .base import ClimateProvider, ClimateProviderError, MonthlyClimateSummary

ARCHIVE_API_URL = "https://archive-api.open-meteo.com/v1/archive"
REQUEST_TIMEOUT_SECONDS = 5
# Historical data for a past month never changes, so it can be cached for a
# while (10_EXTERNAL_INTEGRATIONS.md §7).
CACHE_TTL_SECONDS = 60 * 60 * 24 * 7


class OpenMeteoClimateProvider(ClimateProvider):
    """Climate adapter for the free, keyless Open-Meteo Historical Weather API."""

    def get_monthly_climate(
        self, *, latitude: float, longitude: float, month: int, year: int | None = None
    ) -> MonthlyClimateSummary:
        target_year = year or self._most_recent_completed_year(month)
        cache_key = self._cache_key(latitude, longitude, month, target_year)

        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        summary = self._fetch(latitude, longitude, month, target_year)
        cache.set(cache_key, summary, CACHE_TTL_SECONDS)
        return summary

    @staticmethod
    def _most_recent_completed_year(month: int) -> int:
        today = date.today()
        return today.year if today.month > month else today.year - 1

    @staticmethod
    def _cache_key(latitude: float, longitude: float, month: int, year: int) -> str:
        return f"climate:open-meteo:{round(latitude, 2)}:{round(longitude, 2)}:{year}-{month:02d}"

    def _fetch(
        self, latitude: float, longitude: float, month: int, year: int
    ) -> MonthlyClimateSummary:
        start_date = date(year, month, 1)
        end_date = date(year, month, calendar.monthrange(year, month)[1])

        try:
            response = requests.get(
                ARCHIVE_API_URL,
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
                    "timezone": "auto",
                },
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ClimateProviderError("Unable to reach the climate data provider.") from exc

        return self._normalize(response.json(), year=year, month=month)

    @staticmethod
    def _normalize(payload: dict, *, year: int, month: int) -> MonthlyClimateSummary:
        try:
            daily = payload["daily"]
            highs = [v for v in daily["temperature_2m_max"] if v is not None]
            lows = [v for v in daily["temperature_2m_min"] if v is not None]
            precipitation = [v for v in daily["precipitation_sum"] if v is not None]
        except KeyError as exc:
            raise ClimateProviderError(
                "Unexpected response from the climate data provider."
            ) from exc

        if not highs or not lows:
            raise ClimateProviderError(
                "Climate data provider returned no usable data for this period."
            )

        return MonthlyClimateSummary(
            year=year,
            month=month,
            avg_high_c=round(sum(highs) / len(highs), 1),
            avg_low_c=round(sum(lows) / len(lows), 1),
            total_precipitation_mm=round(sum(precipitation), 1) if precipitation else 0.0,
        )
