from django.core.cache import cache

# Conversation Memory (09_AI_ORCHESTRATION.md §7): short-term "conversation
# context" needed to understand the current interaction, deliberately kept
# separate from persistent "traveler memory" (TravelerProfile, Feedback,
# TravelHistoryEntry - already real Postgres models). Backed by Redis via
# Django's cache framework - the same mechanism integrations.climate already
# uses for its own caching - rather than a new relational model, because
# this is explicitly ephemeral, per-conversation state that should expire on
# its own, not something ever queried or reported on.
#
# A TTL and a hard cap on stored turns both exist for the same reason
# (09_AI_ORCHESTRATION.md §13 - "avoid unnecessarily large conversation
# histories"): an abandoned conversation shouldn't grow forever in Redis,
# and every remembered turn is resent to the AI provider on every
# subsequent message, so unbounded history directly costs real money.
CONVERSATION_TTL_SECONDS = 60 * 30  # 30 minutes of inactivity resets the conversation
MAX_HISTORY_MESSAGES = 12  # 6 user/assistant turns


def conversation_key(*, user, session_key: str | None) -> str:
    """Identify which conversation a message belongs to.

    Authenticated users are keyed by their account, so the same
    conversation continues even across devices/sessions - anonymous users
    have no such stable identity, so the Django session (already used for
    auth cookies) is the next best thing.
    """
    if user is not None and getattr(user, "is_authenticated", False):
        return f"chat-history:user:{user.pk}"
    return f"chat-history:session:{session_key}"


def get_history(key: str) -> list[dict]:
    return cache.get(key) or []


def append_turn(key: str, *, user_message: str, assistant_reply: str) -> None:
    """Record one exchange, trimming to the most recent MAX_HISTORY_MESSAGES
    and refreshing the TTL - called once per handled message, regardless of
    which branch (recommendation, feedback, future_intent, off_topic,
    clarification, fallback) produced the reply."""
    history = get_history(key)
    history.append({"role": "user", "content": user_message})
    history.append({"role": "assistant", "content": assistant_reply})
    history = history[-MAX_HISTORY_MESSAGES:]
    cache.set(key, history, CONVERSATION_TTL_SECONDS)


def clear_history(key: str) -> None:
    """Drop whatever short-term context exists for this key - called when
    the traveler explicitly starts a new conversation (2026-09-02, saved-
    conversations feature), so a fresh thread doesn't silently inherit
    context from whatever was last discussed under the same key."""
    cache.delete(key)
