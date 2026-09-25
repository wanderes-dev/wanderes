import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from evaluations.weather_fixtures import (
    FixtureEntry,
    FixtureWeatherProvider,
    MissingWeatherFixtureError,
    fixture_key,
    load_fixture_file,
    save_fixture_file,
)
from integrations.climate.base import ClimateProviderError


def _write_fixture(path: Path, entries: dict) -> None:
    save_fixture_file({"schema_version": "v1", "provenance": [], "entries": entries}, path)


class FixtureKeyTests(SimpleTestCase):
    def test_rounds_coordinates_to_two_decimals(self):
        self.assertEqual(fixture_key(48.85661, 2.35222, 6), fixture_key(48.8566, 2.3522, 6))

    def test_different_months_are_different_keys(self):
        self.assertNotEqual(fixture_key(48.86, 2.35, 6), fixture_key(48.86, 2.35, 7))

    def test_key_never_encodes_year(self):
        # Deliberate: OpenMeteoClimateProvider._most_recent_completed_year()
        # depends on date.today(), so a year-keyed fixture would silently
        # stop matching as real time passes. There's no `year` parameter
        # to this function at all - this test exists so that invariant
        # can't quietly regress if someone "helpfully" adds one later.
        key = fixture_key(48.86, 2.35, 6)
        self.assertNotIn("202", key)


class LoadSaveFixtureFileTests(SimpleTestCase):
    def test_missing_file_returns_empty_valid_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            document = load_fixture_file(Path(tmp) / "does-not-exist.json")
            self.assertEqual(document["entries"], {})
            self.assertEqual(document["schema_version"], "v1")

    def test_save_then_load_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "weather.json"
            entry = {
                "avg_high_c": 25.0,
                "avg_low_c": 18.0,
                "total_precipitation_mm": 5.0,
                "source_year": 2025,
                "captured_at": "2026-09-25T00:00:00+00:00",
            }
            _write_fixture(path, {"48.86,2.35,6": entry})
            document = load_fixture_file(path)
            self.assertEqual(document["entries"]["48.86,2.35,6"], entry)


class FixtureWeatherProviderTests(TestCase):
    def test_known_key_returns_summary_without_any_network_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "weather.json"
            _write_fixture(
                path,
                {
                    fixture_key(48.8566, 2.3522, 6): {
                        "avg_high_c": 25.0,
                        "avg_low_c": 18.0,
                        "total_precipitation_mm": 5.0,
                        "source_year": 2025,
                        "captured_at": "2026-09-25T00:00:00+00:00",
                    }
                },
            )
            provider = FixtureWeatherProvider(path)
            # No mock/patch on requests/urllib here on purpose - if this
            # provider ever grew a network fallback, this test would just
            # hang or error against a real socket instead of proving the
            # point via a mock that could itself be wrong.
            summary = provider.get_monthly_climate(latitude=48.8566, longitude=2.3522, month=6)
            self.assertEqual(summary.avg_high_c, 25.0)
            self.assertEqual(summary.year, 2025)

    def test_missing_key_raises_missing_weather_fixture_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = FixtureWeatherProvider(Path(tmp) / "empty.json")
            with self.assertRaises(MissingWeatherFixtureError):
                provider.get_monthly_climate(latitude=1.0, longitude=1.0, month=1)

    def test_missing_weather_fixture_error_is_not_a_climate_provider_error(self):
        # Deliberate: MissingWeatherFixtureError must NOT subclass
        # ClimateProviderError, or it would be silently swallowed by
        # production code's existing `except ClimateProviderError:
        # continue` in recommendations.scoring, defeating the entire
        # point of surfacing it distinctly to the evaluation runner as
        # a DEPENDENCY_FAILURE rather than a normal scoring miss.
        self.assertFalse(issubclass(MissingWeatherFixtureError, ClimateProviderError))

    def test_empty_fixture_provider_is_still_truthy(self):
        # Real bug found while running the corpus for real: this class
        # defines __len__, and Python falls back to it for truthiness
        # when __bool__ isn't defined - so a freshly-captured fixture
        # with zero entries was `falsy`, and every
        # `climate_provider or get_climate_provider()` fallback already
        # present in production code (recommendations.scoring,
        # ai.orchestration) silently swapped in the REAL, LIVE Open-Meteo
        # provider instead of raising MissingWeatherFixtureError -
        # exactly the silent-live-network-fallback this module exists to
        # prevent. Confirmed live: an evaluation run against a
        # zero-entry fixture made real HTTP calls to Open-Meteo instead
        # of failing closed.
        with tempfile.TemporaryDirectory() as tmp:
            provider = FixtureWeatherProvider(Path(tmp) / "empty.json")
            self.assertEqual(len(provider), 0)
            self.assertTrue(bool(provider))
            self.assertIs(provider or "would be the live provider in production code", provider)

    def test_len_and_coverage_keys_reflect_loaded_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "weather.json"
            key = fixture_key(10.0, 10.0, 3)
            _write_fixture(
                path,
                {
                    key: {
                        "avg_high_c": 30.0,
                        "avg_low_c": 20.0,
                        "total_precipitation_mm": 0.0,
                        "source_year": 2024,
                        "captured_at": "2026-09-25T00:00:00+00:00",
                    }
                },
            )
            provider = FixtureWeatherProvider(path)
            self.assertEqual(len(provider), 1)
            self.assertEqual(provider.coverage_keys(), frozenset({key}))

    def test_default_path_provider_never_touches_network(self):
        # evaluations.runner.run_scenarios() defaults climate_provider to
        # FixtureWeatherProvider() with no path argument at all - this
        # confirms constructing it that way is still purely file-backed,
        # not a fallback to the live integrations.climate provider.
        with patch("evaluations.weather_fixtures.FIXTURE_PATH") as mock_path:
            mock_path.exists.return_value = False
            provider = FixtureWeatherProvider()
        self.assertEqual(len(provider), 0)


class FixtureEntryTests(SimpleTestCase):
    def test_to_summary_uses_source_year_not_requested_year(self):
        entry = FixtureEntry(
            avg_high_c=22.0,
            avg_low_c=12.0,
            total_precipitation_mm=3.0,
            source_year=2023,
            captured_at="2026-09-25T00:00:00+00:00",
        )
        summary = entry.to_summary(9)
        self.assertEqual(summary.year, 2023)
        self.assertEqual(summary.month, 9)
