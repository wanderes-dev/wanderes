from unittest.mock import Mock, patch

import requests
from django.core.cache import cache
from django.test import TestCase, override_settings

from integrations.videos import get_video_provider
from integrations.videos.base import DestinationVideo, VideoProviderError
from integrations.videos.youtube import YouTubeVideoProvider


def _fake_response(items):
    response = Mock()
    response.raise_for_status = Mock()
    response.json.return_value = {"items": items}
    return response


def _fake_item(video_id="abc123", title="Bali Travel Guide", channel_title="Some Channel"):
    return {
        "id": {"videoId": video_id},
        "snippet": {"title": title, "channelTitle": channel_title},
    }


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    YOUTUBE_API_KEY="test-key",
)
class YouTubeVideoProviderTests(TestCase):
    def setUp(self):
        self.provider = YouTubeVideoProvider()
        cache.clear()

    @patch("integrations.videos.youtube.requests.get")
    def test_happy_path_parses_first_result(self, mock_get):
        mock_get.return_value = _fake_response([_fake_item()])

        video = self.provider.get_destination_video(query="Bali Indonesia travel")

        self.assertEqual(video, DestinationVideo("abc123", "Bali Travel Guide", "Some Channel"))
        mock_get.assert_called_once()

    @patch("integrations.videos.youtube.requests.get")
    def test_result_is_cached(self, mock_get):
        mock_get.return_value = _fake_response([_fake_item()])

        self.provider.get_destination_video(query="Bali Indonesia travel")
        self.provider.get_destination_video(query="Bali Indonesia travel")

        mock_get.assert_called_once()

    @patch("integrations.videos.youtube.requests.get")
    def test_empty_results_returns_none_without_error(self, mock_get):
        mock_get.return_value = _fake_response([])

        video = self.provider.get_destination_video(query="a place nobody made a video about")

        self.assertIsNone(video)

    @patch("integrations.videos.youtube.requests.get")
    def test_network_failure_raises_video_provider_error(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("boom")

        with self.assertRaises(VideoProviderError):
            self.provider.get_destination_video(query="Bali Indonesia travel")

    @patch("integrations.videos.youtube.requests.get")
    def test_malformed_response_raises_video_provider_error(self, mock_get):
        response = Mock()
        response.raise_for_status = Mock()
        response.json.return_value = {"unexpected": "shape"}
        mock_get.return_value = response

        with self.assertRaises(VideoProviderError):
            self.provider.get_destination_video(query="Bali Indonesia travel")

    @override_settings(YOUTUBE_API_KEY="")
    @patch("integrations.videos.youtube.requests.get")
    def test_blank_api_key_returns_none_without_network_call(self, mock_get):
        video = self.provider.get_destination_video(query="Bali Indonesia travel")

        self.assertIsNone(video)
        mock_get.assert_not_called()


class VideoProviderFactoryTests(TestCase):
    def test_default_provider_is_youtube(self):
        provider = get_video_provider()

        self.assertIsInstance(provider, YouTubeVideoProvider)

    @override_settings(VIDEO_PROVIDER="not-a-real-provider")
    def test_unknown_provider_raises(self):
        from django.core.exceptions import ImproperlyConfigured

        with self.assertRaises(ImproperlyConfigured):
            get_video_provider()
