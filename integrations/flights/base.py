from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime, timedelta


@dataclass(frozen=True)
class FlightOption:
    """Normalized flight search result, independent of the provider's own
    response shape (§13.2). Every flight adapter returns these, never a
    raw provider response, so scoring/the chat UI never need to know
    which provider produced a given option.

    No raw commission/payout figure on purpose - per §13.3, flight
    options get scored on genuine fit (price, convenience, stops,
    timing), never on which provider pays Wanderes more. Keeping that
    data out of the dataclass entirely is a structural guard against it
    leaking into scoring.
    """

    provider: str
    provider_reference: str
    origin: str
    destination: str
    departure: datetime
    arrival: datetime
    duration: timedelta
    stops: int
    cabin: str
    price: float
    currency: str
    baggage_information: str
    booking_url: str


class FlightProviderError(Exception):
    """Raised when a flight provider is unreachable or returns unusable data.

    Callers should treat this as an external-provider failure (mirrors
    integrations.climate.ClimateProviderError and ai.provider.AIProviderError)
    - handle it gracefully rather than letting raw provider details reach
    the user.
    """


class FlightProvider(ABC):
    """Internal Travel Data Interface for flight search - scaffolded
    ahead of a concrete adapter (DECISIONS_PENDING.md §4,
    10_EXTERNAL_INTEGRATIONS.md §13 has the full research behind this
    shape).

    The rest of the app depends on this interface, never on a specific
    provider's client directly (§3) - a concrete provider gets added by
    implementing this interface and pointing settings.FLIGHT_PROVIDER at
    it, via get_flight_provider()'s factory (same shape as
    get_climate_provider() and ai.provider.get_ai_provider()).
    """

    @abstractmethod
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
        """Search for flights, returning normalized FlightOption results.

        `origin`/`destination` are IATA airport or city codes.
        `return_date` is omitted for a one-way search. `cabin`, when given,
        is a plain string (e.g. "economy", "business") - adapters should
        translate it to whatever the underlying provider's API expects.
        """

    @abstractmethod
    def get_flight_details(self, provider_reference: str) -> FlightOption:
        """Look up one previously-returned flight option by its
        provider_reference (e.g. to re-confirm price/availability
        immediately before showing a "book" link - prices are highly
        dynamic, per 10_EXTERNAL_INTEGRATIONS.md §13.5, and should not be
        treated as valid indefinitely after the original search)."""

    @abstractmethod
    def build_affiliate_link(self, option: FlightOption) -> str:
        """Return the URL the traveler should be sent to in order to book
        this option - an affiliate/deep link for a pure-referral provider,
        or a hosted checkout URL for a book-through-API provider. Kept as
        its own method (rather than assuming FlightOption.booking_url is
        always final) since some providers need a fresh link generated per
        click for attribution tracking."""
