from datetime import date

from .base import HotelOption, HotelProvider

# 2026-09-04, direct request: "prepare our project to receive the booking
# affiliate API for accommodations, so implementing it later is all
# that's left to do" - mirrors the 2026-09-02 KAYAK flight request
# exactly (integrations/flights/kayak.py). This adapter is deliberately a
# skeleton, not a working implementation: Booking.com's Affiliate Partner
# Program is application-reviewed (DECISIONS_PENDING.md §4's research) -
# approved partners get a real XML feed (hotel info, photos, real-time
# pricing/availability), but its exact request/response shape isn't
# public before approval. Every method below raises NotImplementedError
# with a clear pointer to what real work replaces it, rather than
# guessing at a feed format from unavailable documentation and shipping
# code that looks done but silently wouldn't work - the interface
# (HotelProvider, HotelOption) is the part that's genuinely ready now;
# only this file's method bodies are not.
#
# Once Booking.com Affiliate Partner Program access/documentation is
# available, filling in these three methods (following whatever the real
# XML feed's shape turns out to be, normalized into HotelOption per
# base.py) is the only change needed anywhere in the app -
# get_hotel_provider() and everything that will eventually call it
# already depend on the HotelProvider interface, never on this class
# directly.
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
