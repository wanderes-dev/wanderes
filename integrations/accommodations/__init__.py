from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

from .base import AccommodationSearchLinkProvider

__all__ = [
    "AccommodationSearchLinkProvider",
    "get_accommodation_search_link_provider",
]

# Maps a settings.ACCOMMODATION_SEARCH_PROVIDER key to the adapter that
# implements it - same pattern as every other get_*_provider() factory in
# this package. Booking.com is the one real adapter, chosen and validated
# in production (2026-09-23) via CJ Deep Link Automation.
_PROVIDER_REGISTRY = {
    "booking_com": "integrations.accommodations.booking_com.BookingComSearchLinkProvider",
}


def get_accommodation_search_link_provider() -> AccommodationSearchLinkProvider:
    provider_key = getattr(settings, "ACCOMMODATION_SEARCH_PROVIDER", "booking_com")
    try:
        provider_path = _PROVIDER_REGISTRY[provider_key]
    except KeyError as exc:
        raise ImproperlyConfigured(
            f"Unknown ACCOMMODATION_SEARCH_PROVIDER '{provider_key}'."
        ) from exc

    provider_class = import_string(provider_path)
    return provider_class()
