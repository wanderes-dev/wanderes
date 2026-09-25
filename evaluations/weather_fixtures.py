"""Deterministic weather fixtures for evaluation - a version-controlled
snapshot of real `MonthlyClimateSummary` data, served through the exact
same `ClimateProvider` interface production code depends on
(`integrations.climate.base.ClimateProvider`), so nothing in
`evaluations/` or `ai.orchestration`/`recommendations.scoring` needs to
know it isn't talking to the real Open-Meteo adapter.

Why this exists (Cycle 1 -> Cycle 1.5, 2026-09-25): "is Wanderes'
recommendation logic correct" and "is Open-Meteo up right now" are two
different questions, and Cycle 1's comparison run answered both at
once by accident - several scenarios got reported as recommendation/
scoring failures purely because Open-Meteo's free-tier *daily* request
quota ran out mid-run (confirmed via a raw HTTP call returning
`429 Daily API request limit exceeded. Please try again tomorrow.`),
with correct extraction and unrelated production code. A benchmark
answering the first question must not depend on the second.

Fixtures are keyed by `(round(latitude, 2), round(longitude, 2), month)`
only - deliberately NOT by year.
`integrations.climate.open_meteo.OpenMeteoClimateProvider._most_recent_completed_year()`
picks a different year depending on when it happens to run (today's
date) - a year-keyed fixture would silently stop matching as real time
passes, exactly the non-reproducibility this exists to eliminate. A
fixture entry represents "a real, once-observed value for this month",
the same "typical month" stand-in `ClimateProvider.get_monthly_climate`'s
own docstring already describes for a bare `year=None` call - not a
specific year, and never a fabricated one.

Fails closed, always: a coordinate/month pair with no fixture entry
raises `MissingWeatherFixtureError` - this class never makes a network
call under any circumstance. `evaluations.runner` catches this
specifically and classifies it as `DEPENDENCY_FAILURE` (see
evaluations.taxonomy), never as a scoring/quality failure.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from integrations.climate.base import ClimateProvider, MonthlyClimateSummary

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "weather.json"

# Bumped whenever the fixture *format* changes (not its content) - a run
# artifact records this so an old comparison can tell whether the
# fixture schema itself moved on.
FIXTURE_SCHEMA_VERSION = "v1"


class MissingWeatherFixtureError(Exception):
    """Raised by FixtureWeatherProvider when a (latitude, longitude,
    month) triple has no captured entry. Never caught and silently
    papered over with a live request - evaluations.runner treats this
    as a DEPENDENCY_FAILURE, distinct from every real quality-failure
    category."""

    def __init__(self, latitude: float, longitude: float, month: int):
        self.latitude = latitude
        self.longitude = longitude
        self.month = month
        super().__init__(
            f"EVALUATION_INFRASTRUCTURE: missing weather fixture for "
            f"({round(latitude, 2)}, {round(longitude, 2)}, month={month}) - "
            f"run `python manage.py refresh_weather_fixtures` to capture it "
            f"(requires live Open-Meteo access)."
        )


def fixture_key(latitude: float, longitude: float, month: int) -> str:
    return f"{round(latitude, 2)},{round(longitude, 2)},{month}"


@dataclass(frozen=True)
class FixtureEntry:
    avg_high_c: float
    avg_low_c: float
    total_precipitation_mm: float
    source_year: int
    captured_at: str

    def to_summary(self, month: int) -> MonthlyClimateSummary:
        return MonthlyClimateSummary(
            year=self.source_year,
            month=month,
            avg_high_c=self.avg_high_c,
            avg_low_c=self.avg_low_c,
            total_precipitation_mm=self.total_precipitation_mm,
        )


def load_fixture_file(path: Path | None = None) -> dict:
    """Returns the raw fixture document ({"schema_version", "provenance",
    "entries"}). A missing file is treated as an empty, valid fixture
    (schema_version current, no entries) rather than an error - a fresh
    checkout with no fixtures captured yet is a normal starting state."""
    fixture_path = path or FIXTURE_PATH
    if not fixture_path.exists():
        return {"schema_version": FIXTURE_SCHEMA_VERSION, "provenance": [], "entries": {}}
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def save_fixture_file(document: dict, path: Path | None = None) -> None:
    fixture_path = path or FIXTURE_PATH
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    fixture_path.write_text(
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )


class FixtureWeatherProvider(ClimateProvider):
    """The ClimateProvider evaluations.runner passes by default - reads
    the version-controlled snapshot, never the network. Loads the
    fixture file once at construction (evaluation runs are short-lived
    processes; a file that changes mid-run isn't a real scenario)."""

    def __init__(self, path: Path | None = None):
        document = load_fixture_file(path)
        self._entries: dict[str, FixtureEntry] = {
            key: FixtureEntry(**value) for key, value in document.get("entries", {}).items()
        }

    def get_monthly_climate(
        self, *, latitude: float, longitude: float, month: int, year: int | None = None
    ) -> MonthlyClimateSummary:
        key = fixture_key(latitude, longitude, month)
        entry = self._entries.get(key)
        if entry is None:
            raise MissingWeatherFixtureError(latitude, longitude, month)
        return entry.to_summary(month)

    def __len__(self) -> int:
        return len(self._entries)

    def __bool__(self) -> bool:
        # Without this, Python falls back to __len__ for truthiness - a
        # freshly-captured fixture with zero entries would then be
        # `falsy`, and every `climate_provider or get_climate_provider()`
        # fallback already present in production code (recommendations.
        # scoring, ai.orchestration) would silently swap in the REAL,
        # LIVE Open-Meteo provider instead. That's exactly the silent-
        # live-network-fallback this whole module exists to prevent -
        # confirmed the hard way: a live evaluation run with an empty
        # fixture made 75 real HTTP calls to Open-Meteo per scenario
        # instead of raising MissingWeatherFixtureError. An instance
        # existing and being usable is not the same thing as it having
        # full coverage - len() stays meaningful for introspection/tests,
        # but truthiness must always be True.
        return True

    def coverage_keys(self) -> frozenset[str]:
        return frozenset(self._entries)


def utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()
