from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class AffiliateLinkResult:
    """Normalized affiliate-link search result, regardless of the
    network's own response shape (10_EXTERNAL_INTEGRATIONS.md §13.2 -
    "Normalized internal representations" - same pattern already applied
    to FlightOption/HotelOption).

    Deliberately carries no commission/payout figure - the same
    structural guard already applied to FlightOption/HotelOption
    (10_EXTERNAL_INTEGRATIONS.md §13.3: never let commission influence
    ranking). This dataclass represents "a real link we can send a
    traveler to," not "how much Wanderes would earn from it."
    """

    network: str
    link_id: str
    advertiser_id: str
    advertiser_name: str
    link_name: str
    destination_url: str
    tracking_url: str
    targeted_countries: list[str]


class AffiliateNetworkError(Exception):
    """Raised when an affiliate network is unreachable or returns unusable
    data - mirrors ClimateProviderError/FlightProviderError/
    HotelProviderError/AIProviderError. Callers should handle this
    gracefully rather than letting raw network details reach a user."""


class AffiliateNetworkProvider(ABC):
    """Internal interface for affiliate-link discovery (2026-09-09).

    Deliberately its own interface, not folded into HotelProvider -
    HotelProvider.build_affiliate_link() (integrations/hotels/base.py)
    still requires a real HotelOption as input, which requires
    search_hotels() to work, which still needs Booking.com Demand API
    access that isn't confirmed (10_EXTERNAL_INTEGRATIONS.md §13.8). This
    interface covers what CJ's OWN API can actually do today - discover
    real, trackable links by keyword/country/advertiser, independent of
    property-level search - and is the natural building block for
    BookingComHotelProvider.build_affiliate_link() once search_hotels()
    also becomes real, not a replacement for it.

    A concrete network is added by implementing this interface and
    pointing settings.AFFILIATE_PROVIDER at it, per
    get_affiliate_network_provider()'s factory (same pattern as every
    other provider interface in this app)."""

    @abstractmethod
    def search_links(
        self,
        *,
        advertiser_ids: list[str] | None = None,
        keywords: str | None = None,
        targeted_country: str | None = None,
    ) -> list[AffiliateLinkResult]:
        """Search for real, currently-active affiliate links.

        At least one of advertiser_ids/keywords/targeted_country must be
        given - an unfiltered search is not a supported use (mirrors CJ's
        own Link Search API, which returns zero results for an empty
        request rather than "everything")."""
