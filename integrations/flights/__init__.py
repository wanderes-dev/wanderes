from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

from .base import FlightOption, FlightProvider, FlightProviderError

__all__ = [
    "FlightOption",
    "FlightProvider",
    "FlightProviderError",
    "get_flight_provider",
]

# Maps a settings.FLIGHT_PROVIDER key to the adapter that implements it,
# so switching (or adding) a provider is a settings change, not an
# application-code change (§13.1 - same pattern as get_climate_provider()
# and ai.provider.get_ai_provider()). "kayak" points at a deliberate
# skeleton (integrations/flights/kayak.py), not a working adapter - there
# is no real KAYAK API access to build against yet (DECISIONS_PENDING.md
# §4).
_PROVIDER_REGISTRY = {
    "kayak": "integrations.flights.kayak.KayakFlightProvider",
}


def get_flight_provider() -> FlightProvider:
    provider_key = getattr(settings, "FLIGHT_PROVIDER", "")
    if not provider_key:
        raise ImproperlyConfigured(
            "FLIGHT_PROVIDER is not set. Add it to your .env file (see .env.example) "
            "once a flight provider is ready to use - see DECISIONS_PENDING.md §4."
        )
    try:
        provider_path = _PROVIDER_REGISTRY[provider_key]
    except KeyError as exc:
        raise ImproperlyConfigured(f"Unknown FLIGHT_PROVIDER '{provider_key}'.") from exc

    provider_class = import_string(provider_path)
    return provider_class()
