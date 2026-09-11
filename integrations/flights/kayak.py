from datetime import date

from .base import FlightOption, FlightProvider

# Deliberate skeleton, not a working implementation - KAYAK's API needs
# manual business approval with no public docs until then
# (DECISIONS_PENDING.md §4). Nothing to build against yet. Every method
# below raises NotImplementedError with a pointer to what replaces it,
# rather than guessing at request/response shapes and shipping something
# that looks done but silently doesn't work. The interface
# (FlightProvider, FlightOption) is genuinely ready now; only the method
# bodies here aren't.
#
# Once real API access/docs show up, filling in these three methods
# (normalized into FlightOption per base.py) is the only change needed
# anywhere - get_flight_provider() and its callers already depend on the
# FlightProvider interface, never on this class directly.
KAYAK_API_DOCS_NOTE = (
    "KAYAK flight search is not yet implemented - the API requires manual "
    "business approval with no public documentation until then "
    "(documentation/DECISIONS_PENDING.md §4). Fill in this method once "
    "real API access and documentation are available."
)


class KayakFlightProvider(FlightProvider):
    """Flight adapter for KAYAK - skeleton only, see module docstring."""

    def search_flights(
        self,
        *,
        origin: str,
        destination: str,
        depart_date: date,
        return_date: date | None = None,
        passengers: int = 1,
        cabin: str | None = None,
    ) -> list[FlightOption]:
        raise NotImplementedError(KAYAK_API_DOCS_NOTE)

    def get_flight_details(self, provider_reference: str) -> FlightOption:
        raise NotImplementedError(KAYAK_API_DOCS_NOTE)

    def build_affiliate_link(self, option: FlightOption) -> str:
        raise NotImplementedError(KAYAK_API_DOCS_NOTE)
