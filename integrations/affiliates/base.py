from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class AffiliateLinkResult:
    """Normalized affiliate-link search result, independent of the
    network's own response shape (10_EXTERNAL_INTEGRATIONS.md §13.2,
    same pattern as FlightOption/HotelOption).

    No commission/payout figure on purpose - same structural guard as
    FlightOption/HotelOption (§13.3: commission never influences
    ranking). This represents "a real link we can send a traveler to,"
    not "how much Wanderes would earn from it."
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
    """Internal interface for affiliate-link discovery.

    Kept separate from HotelProvider rather than folded in -
    HotelProvider.build_affiliate_link() (integrations/hotels/base.py)
    needs a real HotelOption from a real search_hotels() implementation,
    which no accommodation provider currently backs (Booking.com was
    ruled out 2026-09-11 - no property-level data feed available to us,
    see DECISIONS_PENDING.md §4). This interface covers what CJ's API can
    do today regardless - discover real, trackable links by
    keyword/country/advertiser, independent of property-level search -
    and stays a useful building block for whichever accommodation
    provider search_hotels() eventually gets built against.

    A concrete network is added by implementing this interface and
    pointing settings.AFFILIATE_PROVIDER at it, per
    get_affiliate_network_provider()'s factory (same pattern as every
    other provider interface here)."""

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
