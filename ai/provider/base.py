from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass


@dataclass(frozen=True)
class AIMessage:
    """One turn in a conversation sent to the AI provider.

    `role` is one of "system", "user", "assistant" - the same vocabulary
    every major chat-completion API uses, so this stays provider-agnostic.
    """

    role: str
    content: str


@dataclass(frozen=True)
class AIResponse:
    """Normalized reply from an AI provider, regardless of its own response shape."""

    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int


class AIProviderError(Exception):
    """Raised when an AI provider is unreachable or returns an unusable response.

    Callers should treat this as an external-provider failure (mirrors
    integrations.climate.ClimateProviderError) - handle it gracefully
    rather than letting raw provider details reach the user.
    """


class AIProvider(ABC):
    """Internal AI Provider Abstraction (05_AI_DESIGN.md §10, 09_AI_ORCHESTRATION.md §11).

    The rest of the application depends on this interface, never on a
    specific provider's SDK directly, so the provider or model can change
    without redesigning the recommendation system. This interface is
    intentionally thin: building the actual conversation context (traveler
    profile, relevant travel data, summarized history) is the orchestration
    layer's job (Phase 9), not the adapter's.
    """

    @abstractmethod
    def generate_reply(
        self, messages: list[AIMessage], *, max_tokens: int | None = None
    ) -> AIResponse:
        """Send a conversation to the provider and return its natural-language reply.

        `messages` should already include any system prompt - this
        interface doesn't inject one itself, so callers stay in control of
        exactly what's sent (09_AI_ORCHESTRATION.md §4: "The application
        decides which information can be included").
        """

    @abstractmethod
    def generate_structured_reply(
        self, messages: list[AIMessage], *, json_schema: dict, max_tokens: int | None = None
    ) -> dict:
        """Send a conversation to the provider and return a parsed JSON dict
        conforming to `json_schema`.

        Used where AI output affects application logic (e.g. intent/constraint
        extraction) - "prefer structured output over parsing arbitrary
        natural language" (09_AI_ORCHESTRATION.md §9). Any provider adapter
        must support this, not just OpenAI, to keep the abstraction real.
        """

    @abstractmethod
    def stream_reply(
        self, messages: list[AIMessage], *, max_tokens: int | None = None
    ) -> Iterator[str]:
        """Send a conversation to the provider and yield its reply incrementally.

        Each yielded string is one content chunk, in order - used for the
        progressive chat UI response (09_AI_ORCHESTRATION.md §8). Raises
        AIProviderError if the request fails before or during streaming.
        """
