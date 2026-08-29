from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from openai import OpenAI, OpenAIError

from .base import AIMessage, AIProvider, AIProviderError, AIResponse

REQUEST_TIMEOUT_SECONDS = 20
# Cost containment default (09_AI_ORCHESTRATION.md §13) - callers can
# override per call via generate_reply(..., max_tokens=...).
DEFAULT_MAX_TOKENS = 600


class OpenAIProvider(AIProvider):
    """AI adapter for OpenAI's Chat Completions API (Phase 2 decision)."""

    def __init__(self):
        if not settings.OPENAI_API_KEY:
            raise ImproperlyConfigured(
                "OPENAI_API_KEY is not set. Add it to your .env file (see .env.example)."
            )
        self._client = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=REQUEST_TIMEOUT_SECONDS)

    def generate_reply(
        self, messages: list[AIMessage], *, max_tokens: int | None = None
    ) -> AIResponse:
        try:
            payload = [{"role": message.role, "content": message.content} for message in messages]
            response = self._client.chat.completions.create(
                model=settings.AI_MODEL,
                messages=payload,
                max_tokens=max_tokens or DEFAULT_MAX_TOKENS,
            )
        except OpenAIError as exc:
            raise AIProviderError("Unable to reach the AI provider.") from exc

        return self._normalize(response)

    @staticmethod
    def _normalize(response) -> AIResponse:
        try:
            content = response.choices[0].message.content
        except (IndexError, AttributeError) as exc:
            raise AIProviderError("Unexpected response from the AI provider.") from exc

        if not content:
            raise AIProviderError("AI provider returned an empty response.")

        usage = response.usage
        return AIResponse(
            content=content,
            model=response.model,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
        )
