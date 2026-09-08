from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

from .base import DestinationVideo, VideoProvider, VideoProviderError

__all__ = [
    "DestinationVideo",
    "VideoProvider",
    "VideoProviderError",
    "get_video_provider",
]

# Maps a short settings.VIDEO_PROVIDER key to the adapter that implements
# it, so switching providers is a settings change, not an application-code
# change (10_EXTERNAL_INTEGRATIONS.md §3 - "Provider replaceability is an
# architectural requirement"), same pattern as integrations.climate.
_PROVIDER_REGISTRY = {
    "youtube": "integrations.videos.youtube.YouTubeVideoProvider",
}


def get_video_provider() -> VideoProvider:
    provider_key = getattr(settings, "VIDEO_PROVIDER", "youtube")
    try:
        provider_path = _PROVIDER_REGISTRY[provider_key]
    except KeyError as exc:
        raise ImproperlyConfigured(f"Unknown VIDEO_PROVIDER '{provider_key}'.") from exc

    provider_class = import_string(provider_path)
    return provider_class()
