from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

from .base import ClimateProvider, ClimateProviderError, MonthlyClimateSummary

__all__ = [
    "ClimateProvider",
    "ClimateProviderError",
    "MonthlyClimateSummary",
    "get_climate_provider",
]

# Maps a short settings.CLIMATE_PROVIDER key to the adapter that implements
# it, so switching providers is a settings change, not an application-code
# change (10_EXTERNAL_INTEGRATIONS.md §3 - "Provider replaceability is an
# architectural requirement").
_PROVIDER_REGISTRY = {
    "open_meteo": "integrations.climate.open_meteo.OpenMeteoClimateProvider",
}


def get_climate_provider() -> ClimateProvider:
    provider_key = getattr(settings, "CLIMATE_PROVIDER", "open_meteo")
    try:
        provider_path = _PROVIDER_REGISTRY[provider_key]
    except KeyError as exc:
        raise ImproperlyConfigured(f"Unknown CLIMATE_PROVIDER '{provider_key}'.") from exc

    provider_class = import_string(provider_path)
    return provider_class()
