from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class DestinationVideo:
    """A real video found for a destination, normalized regardless of
    provider (10_EXTERNAL_INTEGRATIONS.md §4). Carries a bare video_id, not
    a pre-built embed URL - the client builds the embed URL from it, the
    same convention already used for a Destination's slug (the server sends
    the identifier, the client builds /trips/create/?destination=<slug>)."""

    video_id: str
    title: str
    channel_title: str = ""


class VideoProviderError(Exception):
    """Raised when a video provider is unreachable or returns unusable data.

    This is distinct from get_destination_video() returning None, which
    means "the provider was reachable but legitimately has no good result
    (or isn't configured)" - callers should degrade gracefully either way,
    but this exception specifically signals an external-provider failure
    worth logging (10_EXTERNAL_INTEGRATIONS.md §8).
    """


class VideoProvider(ABC):
    """Internal Travel Data Interface for destination videos.

    The rest of the application depends on this interface, never on a
    specific provider's client library directly (10_EXTERNAL_INTEGRATIONS.md
    §3) - so the provider can be replaced by implementing this interface
    again and pointing settings.VIDEO_PROVIDER at it.
    """

    @abstractmethod
    def get_destination_video(self, *, query: str) -> DestinationVideo | None:
        """Return a real video matching the query, or None if there isn't a
        good one (or the provider isn't configured - e.g. no API key set).
        Never invents a result - see 05_AI_DESIGN.md §7's "never invent
        travel data" principle, which applies to this UI-facing data too."""
