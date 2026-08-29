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


class AIProviderFactoryTests(TestCase):
    @override_settings(OPENAI_API_KEY="test-key")
    def test_default_provider_is_openai(self):
        provider = get_ai_provider()

        self.assertIsInstance(provider, OpenAIProvider)

    @override_settings(AI_PROVIDER="not-a-real-provider")
    def test_unknown_provider_raises(self):
        with self.assertRaises(ImproperlyConfigured):
            get_ai_provider()
