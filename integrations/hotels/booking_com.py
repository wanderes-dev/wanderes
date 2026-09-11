from datetime import date

from .base import HotelOption, HotelProvider

# Same situation as the KAYAK flight skeleton (integrations/flights/
# kayak.py): deliberately not a working implementation. Booking.com's
# Affiliate Partner Program is application-reviewed
# (DECISIONS_PENDING.md §4) - approved partners get a real XML feed
# (hotel info, photos, real-time pricing/availability), but the exact
# shape isn't public before approval. Every method below raises
# NotImplementedError with a pointer to what replaces it, rather than
# guessing at a feed format and shipping something that looks done but
# silently doesn't work. The interface (HotelProvider, HotelOption) is
# genuinely ready now; only the method bodies here aren't.
#
# Once real access/docs show up, filling in these three methods
# (normalized into HotelOption per base.py) is the only change needed
# anywhere - get_hotel_provider() and its callers already depend on the
# HotelProvider interface, never on this class directly.
BOOKING_COM_API_DOCS_NOTE = (
    "Booking.com hotel search is not yet implemented - the Affiliate "
    "Partner Program is application-reviewed, and its real XML feed "
    "format isn't public until approved (documentation/DECISIONS_PENDING.md "
    "§4). Fill in this method once real API access and documentation are "
    "available."
)


class BookingComHotelProvider(HotelProvider):
    """Hotel adapter for Booking.com - skeleton only, see module docstring."""

    def search_hotels(
        self,
        *,
        destination: str,
        check_in: date,
        check_out: date,
        guests: int = 1,
    ) -> list[HotelOption]:
        raise NotImplementedError(BOOKING_COM_API_DOCS_NOTE)

    def get_hotel_details(self, provider_reference: str) -> HotelOption:
        raise NotImplementedError(BOOKING_COM_API_DOCS_NOTE)

    def build_affiliate_link(self, option: HotelOption) -> str:
        raise NotImplementedError(BOOKING_COM_API_DOCS_NOTE)
