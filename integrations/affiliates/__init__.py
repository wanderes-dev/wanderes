from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

from .base import AffiliateLinkResult, AffiliateNetworkError, AffiliateNetworkProvider

__all__ = [
    "AffiliateLinkResult",
    "AffiliateNetworkError",
    "AffiliateNetworkProvider",
    "get_affiliate_network_provider",
]

# Maps a short settings.AFFILIATE_PROVIDER key to the adapter that
# implements it - same swappable-via-settings pattern as every other
# provider interface in this app (integrations.climate.
# get_climate_provider(), integrations.flights.get_flight_provider(),
# integrations.hotels.get_hotel_provider(), ai.provider.get_ai_provider()).
_PROVIDER_REGISTRY = {
    "cj": "integrations.affiliates.cj.CJAffiliateProvider",
}


def get_affiliate_network_provider() -> AffiliateNetworkProvider:
    provider_key = getattr(settings, "AFFILIATE_PROVIDER", "")
    if not provider_key:
        raise ImproperlyConfigured(
            "AFFILIATE_PROVIDER is not set. Add it to your .env file (see .env.example) "
            "once CJ_API_TOKEN and CJ_WEBSITE_ID are both configured."
        )
    try:
        provider_path = _PROVIDER_REGISTRY[provider_key]
    except KeyError as exc:
        raise ImproperlyConfigured(f"Unknown AFFILIATE_PROVIDER '{provider_key}'.") from exc

    provider_class = import_string(provider_path)
    return provider_class()
