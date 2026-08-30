import json
from collections.abc import Iterator

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
        response = self._complete(messages, max_tokens=max_tokens)
        content = self._extract_content(response)
        return self._normalize(response, content)

    def generate_structured_reply(
        self,
        messages: list[AIMessage],
        *,
        json_schema: dict,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict:
        response = self._complete(
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
            response_format={"type": "json_schema", "json_schema": json_schema},
        )
        content = self._extract_content(response)
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise AIProviderError("AI provider returned invalid JSON.") from exc

    def stream_reply(
        self, messages: list[AIMessage], *, max_tokens: int | None = None
    ) -> Iterator[str]:
        payload = [{"role": message.role, "content": message.content} for message in messages]
        try:
            stream = self._client.chat.completions.create(
                model=settings.AI_MODEL,
                messages=payload,
                max_tokens=max_tokens or DEFAULT_MAX_TOKENS,
                stream=True,
            )
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except OpenAIError as exc:
            raise AIProviderError("Unable to reach the AI provider.") from exc

    def _complete(
        self, messages: list[AIMessage], *, max_tokens=None, response_format=None, temperature=None
    ):
        try:
            payload = [{"role": message.role, "content": message.content} for message in messages]
            kwargs = {}
            if response_format is not None:
                kwargs["response_format"] = response_format
            if temperature is not None:
                kwargs["temperature"] = temperature
            return self._client.chat.completions.create(
                model=settings.AI_MODEL,
                messages=payload,
                max_tokens=max_tokens or DEFAULT_MAX_TOKENS,
                **kwargs,
            )
        except OpenAIError as exc:
            raise AIProviderError("Unable to reach the AI provider.") from exc

    @staticmethod
    def _extract_content(response) -> str:
        try:
            content = response.choices[0].message.content
        except (IndexError, AttributeError) as exc:
            raise AIProviderError("Unexpected response from the AI provider.") from exc

        if not content:
            raise AIProviderError("AI provider returned an empty response.")
        return content

    @staticmethod
    def _normalize(response, content: str) -> AIResponse:
        usage = response.usage
        return AIResponse(
            content=content,
            model=response.model,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
        )
