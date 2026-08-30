from unittest.mock import Mock, patch

from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings
from openai import OpenAIError

from ai.provider import get_ai_provider
from ai.provider.base import AIMessage, AIProviderError, AIResponse
from ai.provider.openai_provider import OpenAIProvider


def _fake_completion(content="Hello traveler!", model="gpt-4o-mini"):
    response = Mock()
    response.choices = [Mock(message=Mock(content=content))]
    response.model = model
    response.usage = Mock(prompt_tokens=10, completion_tokens=5)
    return response


def _fake_stream_chunks(pieces):
    for piece in pieces:
        chunk = Mock()
        chunk.choices = [Mock(delta=Mock(content=piece))]
        yield chunk


@override_settings(OPENAI_API_KEY="test-key", AI_MODEL="gpt-4o-mini")
class OpenAIProviderTests(TestCase):
    @patch("ai.provider.openai_provider.OpenAI")
    def test_generate_reply_returns_normalized_response(self, mock_openai_class):
        mock_client = Mock()
        mock_client.chat.completions.create.return_value = _fake_completion()
        mock_openai_class.return_value = mock_client

        provider = OpenAIProvider()
        result = provider.generate_reply(
            [AIMessage(role="user", content="Where is warm in October?")]
        )

        expected = AIResponse(
            content="Hello traveler!", model="gpt-4o-mini", prompt_tokens=10, completion_tokens=5
        )
        self.assertEqual(result, expected)
        mock_client.chat.completions.create.assert_called_once()

    @patch("ai.provider.openai_provider.OpenAI")
    def test_provider_error_wraps_openai_error(self, mock_openai_class):
        mock_client = Mock()
        mock_client.chat.completions.create.side_effect = OpenAIError("boom")
        mock_openai_class.return_value = mock_client

        provider = OpenAIProvider()

        with self.assertRaises(AIProviderError):
            provider.generate_reply([AIMessage(role="user", content="hi")])

    @patch("ai.provider.openai_provider.OpenAI")
    def test_empty_content_raises_provider_error(self, mock_openai_class):
        mock_client = Mock()
        mock_client.chat.completions.create.return_value = _fake_completion(content="")
        mock_openai_class.return_value = mock_client

        provider = OpenAIProvider()

        with self.assertRaises(AIProviderError):
            provider.generate_reply([AIMessage(role="user", content="hi")])

    @override_settings(OPENAI_API_KEY="")
    def test_missing_api_key_raises_improperly_configured(self):
        with self.assertRaises(ImproperlyConfigured):
            OpenAIProvider()

    @patch("ai.provider.openai_provider.OpenAI")
    def test_generate_structured_reply_returns_parsed_json(self, mock_openai_class):
        mock_client = Mock()
        mock_client.chat.completions.create.return_value = _fake_completion(
            content='{"month": 10, "is_travel_request": true}'
        )
        mock_openai_class.return_value = mock_client

        provider = OpenAIProvider()
        result = provider.generate_structured_reply(
            [AIMessage(role="user", content="somewhere warm in October")],
            json_schema={"name": "test_schema", "strict": True, "schema": {}},
        )

        self.assertEqual(result, {"month": 10, "is_travel_request": True})
        _, kwargs = mock_client.chat.completions.create.call_args
        self.assertEqual(kwargs["response_format"]["type"], "json_schema")
        self.assertNotIn("temperature", kwargs)

    @patch("ai.provider.openai_provider.OpenAI")
    def test_generate_structured_reply_passes_temperature_when_given(self, mock_openai_class):
        # Intent extraction calls this with temperature=0 for consistent
        # results across near-identical calls - confirms it actually
        # reaches the provider rather than being silently dropped.
        mock_client = Mock()
        mock_client.chat.completions.create.return_value = _fake_completion(content='{"a": 1}')
        mock_openai_class.return_value = mock_client

        provider = OpenAIProvider()
        provider.generate_structured_reply(
            [AIMessage(role="user", content="hi")],
            json_schema={"name": "test_schema", "strict": True, "schema": {}},
            temperature=0,
        )

        _, kwargs = mock_client.chat.completions.create.call_args
        self.assertEqual(kwargs["temperature"], 0)

    @patch("ai.provider.openai_provider.OpenAI")
    def test_generate_structured_reply_raises_on_invalid_json(self, mock_openai_class):
        mock_client = Mock()
        mock_client.chat.completions.create.return_value = _fake_completion(content="not json")
        mock_openai_class.return_value = mock_client

        provider = OpenAIProvider()

        with self.assertRaises(AIProviderError):
            provider.generate_structured_reply(
                [AIMessage(role="user", content="hi")],
                json_schema={"name": "test_schema", "strict": True, "schema": {}},
            )

    @patch("ai.provider.openai_provider.OpenAI")
    def test_stream_reply_yields_chunks_in_order(self, mock_openai_class):
        mock_client = Mock()
        mock_client.chat.completions.create.return_value = _fake_stream_chunks(
            ["Hello", " there", "!"]
        )
        mock_openai_class.return_value = mock_client

        provider = OpenAIProvider()
        chunks = list(provider.stream_reply([AIMessage(role="user", content="hi")]))

        self.assertEqual(chunks, ["Hello", " there", "!"])
        _, kwargs = mock_client.chat.completions.create.call_args
        self.assertTrue(kwargs["stream"])

    @patch("ai.provider.openai_provider.OpenAI")
    def test_stream_reply_raises_on_error_before_streaming(self, mock_openai_class):
        mock_client = Mock()
        mock_client.chat.completions.create.side_effect = OpenAIError("boom")
        mock_openai_class.return_value = mock_client

        provider = OpenAIProvider()

        with self.assertRaises(AIProviderError):
            list(provider.stream_reply([AIMessage(role="user", content="hi")]))

    @patch("ai.provider.openai_provider.OpenAI")
    def test_stream_reply_raises_on_error_mid_stream(self, mock_openai_class):
        def failing_stream():
            yield from _fake_stream_chunks(["Hello"])
            raise OpenAIError("connection dropped")

        mock_client = Mock()
        mock_client.chat.completions.create.return_value = failing_stream()
        mock_openai_class.return_value = mock_client

        provider = OpenAIProvider()

        with self.assertRaises(AIProviderError):
            list(provider.stream_reply([AIMessage(role="user", content="hi")]))


class AIProviderFactoryTests(TestCase):
    @override_settings(OPENAI_API_KEY="test-key")
    def test_default_provider_is_openai(self):
        provider = get_ai_provider()

        self.assertIsInstance(provider, OpenAIProvider)

    @override_settings(AI_PROVIDER="not-a-real-provider")
    def test_unknown_provider_raises(self):
        with self.assertRaises(ImproperlyConfigured):
            get_ai_provider()
