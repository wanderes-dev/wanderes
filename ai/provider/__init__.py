from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

from .base import AIMessage, AIProvider, AIProviderError, AIResponse

__all__ = [
    "AIMessage",
    "AIProvider",
    "AIProviderError",
    "AIResponse",
    "get_ai_provider",
]

# Maps a short settings.AI_PROVIDER key to the adapter that implements it,
# so switching providers is a settings change, not an application-code
# change - same pattern as integrations.climate's provider registry.
_PROVIDER_REGISTRY = {
    "openai": "ai.provider.openai_provider.OpenAIProvider",
}


def get_ai_provider() -> AIProvider:
    provider_key = getattr(settings, "AI_PROVIDER", "openai")
    try:
        provider_path = _PROVIDER_REGISTRY[provider_key]
    except KeyError as exc:
        raise ImproperlyConfigured(f"Unknown AI_PROVIDER '{provider_key}'.") from exc

    provider_class = import_string(provider_path)
    return provider_class()
