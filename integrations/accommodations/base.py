from abc import ABC, abstractmethod
from datetime import date


class AccommodationSearchLinkProvider(ABC):
    """Internal interface for outbound accommodation search links.

    Deliberately not shaped like integrations.hotels.HotelProvider - that
    one models real inventory search (search/details/affiliate-link-from-
    a-result), which assumes API access Wanderes doesn't have for any
    accommodation provider today (see DECISIONS_PENDING.md §4 - Booking.com
    confirmed no property-level feed is available to our publisher
    category). This interface only ever builds a search URL the traveler
    is sent to on an external site; Wanderes never sees or stores search
    results. A concrete provider gets added by implementing this and
    pointing settings.ACCOMMODATION_SEARCH_PROVIDER at it, via
    get_accommodation_search_link_provider()'s factory - same shape as
    every other get_*_provider() in this package.
    """

    @abstractmethod
    def build_search_url(
        self,
        *,
        destination: str,
        country: str = "",
        check_in: date | None = None,
        check_out: date | None = None,
        adults: int | None = None,
        children: int | None = None,
        child_ages: list[int] | None = None,
        rooms: int | None = None,
    ) -> str:
        """Return a search-results URL for this destination.

        Every field past `destination` is optional and should be omitted
        entirely (not guessed) when Wanderes doesn't actually know it -
        the live chat recommendation flow only ever knows a destination
        name and country, never real dates or party size. Implementations
        must degrade gracefully to a destination-only search rather than
        fabricate any of these.
        """
