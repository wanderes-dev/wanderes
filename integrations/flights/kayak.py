from datetime import date

from .base import FlightOption, FlightProvider

# 2026-09-02, direct request: "leave it ready to receive a flight source
# from KAYAK, so implementing it later is all that's left to do." This
# adapter is deliberately a skeleton, not a working implementation -
# KAYAK's API requires manual business approval with no public
# documentation until then (see DECISIONS_PENDING.md §4's research), so
# there is nothing real to implement against yet. Every method below
# raises NotImplementedError with a clear pointer to what real work
# replaces it, rather than guessing at request/response shapes from
# unavailable documentation and shipping code that looks done but silently
# wouldn't work - the interface (FlightProvider, FlightOption) is the part
# that's genuinely ready now; only this file's method bodies are not.
#
# Once KAYAK API access/documentation is available, filling in these three
# methods (following whatever their actual request/response shapes turn
# out to be, normalized into FlightOption per base.py) is the only change
# needed anywhere in the app - get_flight_provider() and everything that
# will eventually call it already depend on the FlightProvider interface,
# never on this class directly.
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
