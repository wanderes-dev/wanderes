from datetime import date
from unittest.mock import Mock, patch

import requests
from django.core.cache import cache
from django.test import TestCase, override_settings

from analytics.models import Event
from integrations.climate import get_climate_provider
from integrations.climate.base import ClimateProviderError, MonthlyClimateSummary
from integrations.climate.open_meteo import OpenMeteoClimateProvider


def _fake_response(daily):
    response = Mock()
    response.raise_for_status = Mock()
    response.json.return_value = {"daily": daily}
    return response


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class OpenMeteoClimateProviderTests(TestCase):
    def setUp(self):
        self.provider = OpenMeteoClimateProvider()
        cache.clear()

    @patch("integrations.climate.open_meteo.requests.get")
    def test_get_monthly_climate_averages_daily_values(self, mock_get):
        mock_get.return_value = _fake_response(
            {
                "temperature_2m_max": [20.0, 22.0, 24.0],
                "temperature_2m_min": [10.0, 12.0, 14.0],
                "precipitation_sum": [0.0, 1.5, 0.5],
            }
        )

        summary = self.provider.get_monthly_climate(
            latitude=38.72, longitude=-9.14, month=10, year=2025
        )

        self.assertEqual(summary, MonthlyClimateSummary(2025, 10, 22.0, 12.0, 2.0))
        mock_get.assert_called_once()

    @patch("integrations.climate.open_meteo.requests.get")
    def test_result_is_cached(self, mock_get):
        mock_get.return_value = _fake_response(
            {"temperature_2m_max": [20.0], "temperature_2m_min": [10.0], "precipitation_sum": [0.0]}
        )

        self.provider.get_monthly_climate(latitude=38.72, longitude=-9.14, month=10, year=2025)
        self.provider.get_monthly_climate(latitude=38.72, longitude=-9.14, month=10, year=2025)

        mock_get.assert_called_once()

    @patch("integrations.climate.open_meteo.requests.get")
    def test_network_failure_raises_climate_provider_error(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("boom")

        with self.assertRaises(ClimateProviderError):
            self.provider.get_monthly_climate(latitude=38.72, longitude=-9.14, month=10, year=2025)

    @patch("integrations.climate.open_meteo.requests.get")
    def test_malformed_response_raises_climate_provider_error(self, mock_get):
        mock_get.return_value = _fake_response({"temperature_2m_max": [20.0]})  # missing keys

        with self.assertRaises(ClimateProviderError):
            self.provider.get_monthly_climate(latitude=38.72, longitude=-9.14, month=10, year=2025)

    @patch("integrations.climate.open_meteo.requests.get")
    def test_cache_miss_records_exactly_one_provider_request_completed(self, mock_get):
        # Instrumented at _fetch(), not the public get_monthly_climate()
        # entry point - a miss is the only case that's genuinely "a
        # provider request."
        mock_get.return_value = _fake_response(
            {"temperature_2m_max": [20.0], "temperature_2m_min": [10.0], "precipitation_sum": [0.0]}
        )

        self.provider.get_monthly_climate(latitude=38.72, longitude=-9.14, month=10, year=2025)

        event = Event.objects.get(event_type="provider_request_completed")
        self.assertTrue(event.metadata["success"])
        self.assertEqual(event.metadata["operation"], "open_meteo_monthly_climate")
        self.assertGreaterEqual(event.metadata["latency_ms"], 0)

    @patch("integrations.climate.open_meteo.requests.get")
    def test_cache_hit_records_no_additional_event(self, mock_get):
        mock_get.return_value = _fake_response(
            {"temperature_2m_max": [20.0], "temperature_2m_min": [10.0], "precipitation_sum": [0.0]}
        )

        self.provider.get_monthly_climate(latitude=38.72, longitude=-9.14, month=10, year=2025)
        self.provider.get_monthly_climate(latitude=38.72, longitude=-9.14, month=10, year=2025)

        self.assertEqual(Event.objects.filter(event_type="provider_request_completed").count(), 1)

    @patch("integrations.climate.open_meteo.requests.get")
    def test_network_failure_records_provider_request_completed_as_failed(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("boom")

        with self.assertRaises(ClimateProviderError):
            self.provider.get_monthly_climate(latitude=38.72, longitude=-9.14, month=10, year=2025)

        event = Event.objects.get(event_type="provider_request_completed")
        self.assertFalse(event.metadata["success"])
        # ClimateProviderError, not the underlying ConnectionError - the
        # wrap-and-reraise happens inside the instrumented block, so
        # that's what actually gets recorded (and what every caller of
        # this provider sees and handles).
        self.assertEqual(event.metadata["error_type"], "ClimateProviderError")

    def test_defaults_to_most_recently_completed_month(self):
        today = date.today()
        expected_year = today.year if today.month > 1 else today.year - 1

        self.assertEqual(
            self.provider._most_recent_completed_year(month=1),
            expected_year,
        )


class ClimateProviderFactoryTests(TestCase):
    def test_default_provider_is_open_meteo(self):
        provider = get_climate_provider()

        self.assertIsInstance(provider, OpenMeteoClimateProvider)

    @override_settings(CLIMATE_PROVIDER="not-a-real-provider")
    def test_unknown_provider_raises(self):
        from django.core.exceptions import ImproperlyConfigured

        with self.assertRaises(ImproperlyConfigured):
            get_climate_provider()
