from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class MonthlyClimateSummary:
    """Normalized climate data for one calendar month at one location.

    This is what every climate provider adapter must return, regardless of
    the external API's own response shape (10_EXTERNAL_INTEGRATIONS.md §4:
    "Normalize data into internal representations").
    """

    year: int
    month: int
    avg_high_c: float
    avg_low_c: float
    total_precipitation_mm: float


class ClimateProviderError(Exception):
    """Raised when a climate provider is unreachable or returns unusable data.

    Callers should treat this as an external-provider failure (per
    10_EXTERNAL_INTEGRATIONS.md §8) - handle it gracefully rather than
    letting raw provider details reach the user.
    """


class ClimateProvider(ABC):
    """Internal Travel Data Interface for climate information.

    The rest of the application depends on this interface, never on a
    specific provider's client library directly (10_EXTERNAL_INTEGRATIONS.md
    §3) - so the provider can be replaced by implementing this interface
    again and pointing settings.CLIMATE_PROVIDER at it.
    """

    @abstractmethod
    def get_monthly_climate(
        self, *, latitude: float, longitude: float, month: int, year: int | None = None
    ) -> MonthlyClimateSummary:
        """Return a climate summary for the given month at the given coordinates.

        If `year` is omitted, implementations should use the most recently
        completed occurrence of that month as a simple stand-in for
        "typical" conditions - not a genuine multi-year climatological
        average. This is a deliberate MVP simplification (documented in
        DEVELOPMENT_LOG.md); averaging across several past years is a
        natural future improvement once real usage justifies the added
        complexity and cost.
        """
