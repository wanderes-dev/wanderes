import hashlib

import requests
from django.conf import settings
from django.core.cache import cache

from .base import DestinationVideo, VideoProvider, VideoProviderError

SEARCH_API_URL = "https://www.googleapis.com/youtube/v3/search"
REQUEST_TIMEOUT_SECONDS = 5
# Real travel videos don't go stale the way weather data does - a much
# longer TTL than climate's 7 days conserves the free daily search quota
# (10,000 units/day; one search.list call costs 100 units) once the same
# destinations get looked up repeatedly.
CACHE_TTL_SECONDS = 60 * 60 * 24 * 30


class YouTubeVideoProvider(VideoProvider):
    """Video adapter for the YouTube Data API v3 search endpoint."""

    def get_destination_video(self, *, query: str) -> DestinationVideo | None:
        api_key = getattr(settings, "YOUTUBE_API_KEY", "")
        if not api_key:
            # Same "the affordance quietly doesn't show" convention as
            # GOOGLE_OAUTH_CLIENT_ID/EMAIL_HOST - not configured is not an
            # error, callers just get no video.
            return None

        cache_key = self._cache_key(query)
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        video = self._fetch(query, api_key)
        if video is not None:
            # Only real hits are cached - a genuine no-match is rare enough
            # for real destination queries that re-checking occasionally is
            # cheap, and it avoids needing a separate "no result" sentinel.
            cache.set(cache_key, video, CACHE_TTL_SECONDS)
        return video

    @staticmethod
    def _cache_key(query: str) -> str:
        # Hashed rather than the raw query (unlike climate's numeric,
        # space-free coordinate keys) - a natural-language query contains
        # spaces/punctuation that would trip a memcached-backed cache's key
        # restrictions, even though the Redis backend this project actually
        # uses wouldn't mind.
        digest = hashlib.sha256(query.strip().lower().encode()).hexdigest()
        return f"video:youtube:{digest}"

    def _fetch(self, query: str, api_key: str) -> DestinationVideo | None:
        try:
            response = requests.get(
                SEARCH_API_URL,
                params={
                    "part": "snippet",
                    "type": "video",
                    "maxResults": 1,
                    "safeSearch": "strict",
                    "q": query,
                    "key": api_key,
                },
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise VideoProviderError("Unable to reach the video data provider.") from exc

        return self._normalize(response.json())

    @staticmethod
    def _normalize(payload: dict) -> DestinationVideo | None:
        try:
            items = payload["items"]
        except KeyError as exc:
            raise VideoProviderError("Unexpected response from the video data provider.") from exc

        if not items:
            return None

        try:
            item = items[0]
            video_id = item["id"]["videoId"]
            snippet = item["snippet"]
            title = snippet["title"]
            channel_title = snippet.get("channelTitle", "")
        except KeyError as exc:
            raise VideoProviderError("Unexpected response from the video data provider.") from exc

        return DestinationVideo(video_id=video_id, title=title, channel_title=channel_title)
