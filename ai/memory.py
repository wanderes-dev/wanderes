import re

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


# 2026-09-06 bug: a later turn's intent extraction (ai.orchestration) was
# reading these exact figures back out of conversation history and
# misattributing them to the traveler - e.g. a one-word follow-up like
# "comer" after a reply suggesting destinations with illustrative
# temperatures/cost tiers would set min_temp_c/max_cost_of_living from
# numbers the AI itself had stated, not anything the traveler said. Two
# attempts to fix this by strengthening the extraction prompt were tried
# and reverted - both broke a different, previously-correct case without
# fixing this one (see DEVELOPMENT_LOG.md). This is a structural fix
# instead: strip these figures from what's actually persisted for future
# context, so a later extraction call can never see them at all, whatever
# the model would otherwise do with them.
_TEMPERATURE_PATTERN = re.compile(
    r"-?\d{1,3}(?:[.,]\d+)?\s*(?:-\s*-?\d{1,3}(?:[.,]\d+)?)?\s*°\s*C", re.IGNORECASE
)
_COST_TIER_PATTERN = re.compile(r"\b[1-5]\s*/\s*5\b")


def sanitize_reply_for_context(assistant_reply: str) -> str:
    """Strip temperature (e.g. "31°C", "18-20°C") and cost-tier (e.g.
    "4/5") figures from an assistant reply before it's persisted as
    conversation context. Only affects what gets remembered for later
    extraction - never the reply actually streamed to the traveler, and
    never what's used to generate a saved conversation's title (see
    ai.conversations._generate_subject, which intentionally keeps using
    the raw text). Not exhaustive - only the specific patterns confirmed
    to cause real contamination; see the note above."""
    sanitized = _TEMPERATURE_PATTERN.sub("[temp]", assistant_reply)
    return _COST_TIER_PATTERN.sub("[cost]", sanitized)


def append_turn(key: str, *, user_message: str, assistant_reply: str) -> None:
    """Record one exchange, trimming to the most recent MAX_HISTORY_MESSAGES
    and refreshing the TTL - called once per handled message, regardless of
    which branch (recommendation, feedback, future_intent, off_topic,
    clarification, fallback) produced the reply."""
    history = get_history(key)
    history.append({"role": "user", "content": user_message})
    history.append(
        {"role": "assistant", "content": sanitize_reply_for_context(assistant_reply)}
    )
    history = history[-MAX_HISTORY_MESSAGES:]
    cache.set(key, history, CONVERSATION_TTL_SECONDS)


def clear_history(key: str) -> None:
    """Drop whatever short-term context exists for this key - called when
    the traveler explicitly starts a new conversation (2026-09-02, saved-
    conversations feature), so a fresh thread doesn't silently inherit
    context from whatever was last discussed under the same key."""
    cache.delete(key)


def _profile_confirmed_key(key: str) -> str:
    return f"{key}:profile-confirmed"


def is_profile_confirmed(key: str) -> bool:
    """Whether ai.orchestration has already asked this conversation to
    confirm its TravelerProfile-derived context at least once (2026-09-02,
    "IA must always confirm this information... before suggest any
    destination"). A separate cache key from the turn history above - it
    needs to survive independently of history_override (a saved
    conversation reads its messages from Postgres, not this cache, but
    still needs this same once-per-conversation gate)."""
    return bool(cache.get(_profile_confirmed_key(key)))


def mark_profile_confirmed(key: str) -> None:
    """Record that this conversation's one-time profile confirmation ask
    has happened, so it isn't repeated on every later message. Same TTL as
    the turn history - an abandoned conversation's gate resets along with
    everything else about it once it goes stale."""
    cache.set(_profile_confirmed_key(key), True, CONVERSATION_TTL_SECONDS)
