from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class HotelOption:
    """Normalized hotel search result, regardless of the external
    provider's own response shape (10_EXTERNAL_INTEGRATIONS.md §13.2 -
    "Normalized internal representations"). Every hotel provider adapter
    must return these, never a raw provider response, so the rest of the
    application (scoring, the chat UI) never needs to know which provider
    produced a given option.

    Deliberately does not carry a raw commission/payout figure - per
    10_EXTERNAL_INTEGRATIONS.md §13.3, hotel options must be scored on
    genuine fit (price, rating, location, cancellation terms), never on
    which provider pays Wanderes more; keeping that data out of this
    dataclass entirely is a structural guard against it ever leaking into
    scoring - the same guard already applied to FlightOption.
    """

    provider: str
    provider_reference: str
    destination: str
    name: str
    rating: float
    price: float
    currency: str
    room_information: str
    cancellation_information: str
    amenities: list[str]
    booking_url: str


class HotelProviderError(Exception):
    """Raised when a hotel provider is unreachable or returns unusable data.

    Callers should treat this as an external-provider failure (mirrors
    integrations.flights.FlightProviderError, integrations.climate.
    ClimateProviderError, and ai.provider.AIProviderError) - handle it
    gracefully rather than letting raw provider details reach the user.
    """


class HotelProvider(ABC):
    """Internal Travel Data Interface for hotel/accommodation search
    (2026-09-04, scaffolded ahead of a concrete adapter - see
    DECISIONS_PENDING.md §4 and 10_EXTERNAL_INTEGRATIONS.md §13 for the
    full research/decision record this shape comes from).

    The rest of the application depends on this interface, never on a
    specific provider's API client directly (10_EXTERNAL_INTEGRATIONS.md
    §3) - so a concrete provider is added by implementing this interface
    once and pointing settings.HOTEL_PROVIDER at it, per
    integrations.hotels.get_hotel_provider()'s factory pattern (same shape
    as integrations.flights.get_flight_provider(),
    integrations.climate.get_climate_provider(), and
    ai.provider.get_ai_provider()).
    """

    @abstractmethod
    def search_hotels(
        self,
        *,
        destination: str,
        check_in: date,
        check_out: date,
        guests: int = 1,
    ) -> list[HotelOption]:
        """Search for hotels, returning normalized HotelOption results.

        `destination` is a city/area name or provider-specific location
        code, whichever the underlying provider's API expects - adapters
        are responsible for resolving a plain destination name to
        whatever identifier their own search call needs.
        """

    @abstractmethod
    def get_hotel_details(self, provider_reference: str) -> HotelOption:
        """Look up one previously-returned hotel option by its
        provider_reference (e.g. to re-confirm price/availability
        immediately before showing a "book" link - prices and
        availability are highly dynamic, per
        10_EXTERNAL_INTEGRATIONS.md §13.5, and should not be treated as
        valid indefinitely after the original search)."""

    @abstractmethod
    def build_affiliate_link(self, option: HotelOption) -> str:
        """Return the URL the traveler should be sent to in order to book
        this option - an affiliate/deep link for a pure-referral provider
        (the expected shape for Booking.com's Affiliate Partner Program,
        per DECISIONS_PENDING.md §4). Kept as its own method (rather than
        assuming HotelOption.booking_url is always final) since some
        providers need a fresh link generated per click for attribution
        tracking."""
