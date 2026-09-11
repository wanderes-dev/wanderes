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

# Maps a settings.HOTEL_PROVIDER key to the adapter that implements it,
# so switching (or adding) a provider is a settings change, not an
# application-code change - same pattern as get_flight_provider(),
# get_climate_provider(), and ai.provider.get_ai_provider(). Empty for
# now - Booking.com was ruled out 2026-09-11 (no property-level data feed
# available to Wanderes, see DECISIONS_PENDING.md §4), nothing else has
# been chosen yet.
_PROVIDER_REGISTRY = {}


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
