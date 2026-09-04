from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

from .base import HotelOption, HotelProvider, HotelProviderError

__all__ = [
    "HotelOption",
    "HotelProvider",
    "HotelProviderError",
    "get_hotel_provider",
]

# Maps a short settings.HOTEL_PROVIDER key to the adapter that implements
# it, so switching (or eventually adding) a provider is a settings change,
# not an application-code change (10_EXTERNAL_INTEGRATIONS.md §13.1 - same
# pattern as integrations.flights.get_flight_provider(),
# integrations.climate.get_climate_provider(), and
# ai.provider.get_ai_provider()). "booking_com" is registered against a
# deliberate skeleton (see integrations/hotels/booking_com.py) rather than
# a working adapter - there is no real Booking.com Affiliate Partner
# Program access to implement against yet (DECISIONS_PENDING.md §4).
_PROVIDER_REGISTRY = {
    "booking_com": "integrations.hotels.booking_com.BookingComHotelProvider",
}


def get_hotel_provider() -> HotelProvider:
    provider_key = getattr(settings, "HOTEL_PROVIDER", "")
    if not provider_key:
        raise ImproperlyConfigured(
            "HOTEL_PROVIDER is not set. Add it to your .env file (see .env.example) "
            "once a hotel provider is ready to use - see DECISIONS_PENDING.md §4."
        )
    try:
        provider_path = _PROVIDER_REGISTRY[provider_key]
    except KeyError as exc:
        raise ImproperlyConfigured(f"Unknown HOTEL_PROVIDER '{provider_key}'.") from exc

    provider_class = import_string(provider_path)
    return provider_class()
