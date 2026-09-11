import re

from django.core.cache import cache

# Short-term chat memory - just enough context to follow the current
# conversation, separate from the persistent traveler stuff (profile,
# feedback, history) that lives in Postgres. Redis-backed via Django's
# cache framework, same as integrations.climate's cache - this is
# throwaway state, nothing worth putting in a real table.
#
# The TTL and message cap keep this bounded: an abandoned chat shouldn't
# sit around forever, and every stored turn gets resent to the AI on each
# new message, so a long history is a real cost, not just clutter.
CONVERSATION_TTL_SECONDS = 60 * 30  # resets after 30 min of inactivity
MAX_HISTORY_MESSAGES = 12  # 6 user/assistant turns


def conversation_key(*, user, session_key: str | None) -> str:
    """Which conversation a message belongs to. Logged-in users are keyed
    by account (so it follows them across devices); anonymous visitors
    get keyed by session, since that's all we've got for them."""
    if user is not None and getattr(user, "is_authenticated", False):
        return f"chat-history:user:{user.pk}"
    return f"chat-history:session:{session_key}"


def get_history(key: str) -> list[dict]:
    return cache.get(key) or []


# Intent extraction used to read these numbers back out of history and
# blame them on the traveler - a bare "comer" after we'd mentioned a
# temperature/cost tier could set min_temp_c/max_cost_of_living from
# something WE said. Prompt tweaks didn't hold up, so instead we just
# strip these figures before they're ever saved - can't misread what
# isn't there.
_TEMPERATURE_PATTERN = re.compile(
    r"-?\d{1,3}(?:[.,]\d+)?\s*(?:-\s*-?\d{1,3}(?:[.,]\d+)?)?\s*°\s*C", re.IGNORECASE
)
_COST_TIER_PATTERN = re.compile(r"\b[1-5]\s*/\s*5\b")


def sanitize_reply_for_context(assistant_reply: str) -> str:
    """Strip temperature/cost-tier figures (e.g. "31°C", "4/5") before an
    assistant reply gets saved as context - doesn't touch what's actually
    streamed to the traveler, or the raw text used for a saved
    conversation's title. Only covers the patterns known to cause
    contamination, not a general-purpose scrubber."""
    sanitized = _TEMPERATURE_PATTERN.sub("[temp]", assistant_reply)
    return _COST_TIER_PATTERN.sub("[cost]", sanitized)


def append_turn(key: str, *, user_message: str, assistant_reply: str) -> None:
    """Save one exchange, trim to MAX_HISTORY_MESSAGES, refresh the TTL.
    Called for every handled message no matter which branch produced the
    reply."""
    history = get_history(key)
    history.append({"role": "user", "content": user_message})
    history.append(
        {"role": "assistant", "content": sanitize_reply_for_context(assistant_reply)}
    )
    history = history[-MAX_HISTORY_MESSAGES:]
    cache.set(key, history, CONVERSATION_TTL_SECONDS)


def clear_history(key: str) -> None:
    """Wipe whatever context exists for this key - used when a traveler
    starts a fresh conversation, so it doesn't quietly inherit whatever
    was discussed last time under the same key."""
    cache.delete(key)
    cache.delete(_climate_budget_key(key))


def _climate_budget_key(key: str) -> str:
    return f"{key}:climate-budget"


_NO_CLIMATE_BUDGET = {"min_temp_c": None, "max_temp_c": None, "max_cost_of_living": None}


def get_climate_budget(key: str) -> dict:
    """Accumulated climate/budget constraints for this conversation - built
    up turn by turn by update_climate_budget() below, not re-derived from
    raw history."""
    return cache.get(_climate_budget_key(key)) or dict(_NO_CLIMATE_BUDGET)


def update_climate_budget(
    key: str,
    *,
    min_temp_c: float | None = None,
    max_temp_c: float | None = None,
    max_cost_of_living: int | None = None,
) -> dict:
    """Merge this turn's (history-free) climate/budget signal into what's
    already accumulated - a field only gets overwritten when this call
    actually passes something for it, otherwise the older value sticks.

    This exists because letting intent extraction re-derive these three
    fields from full history every turn wasn't safe - even with numbers
    stripped from old replies, the model could still infer warmth from a
    destination name alone (Phuket, say). Extracting from a single
    isolated message closes that off entirely; this accumulator is what
    lets "praia" then "orçamento baixo" still combine across turns even
    though each extraction only ever sees one message at a time."""
    current = get_climate_budget(key)
    merged = {
        "min_temp_c": min_temp_c if min_temp_c is not None else current["min_temp_c"],
        "max_temp_c": max_temp_c if max_temp_c is not None else current["max_temp_c"],
        "max_cost_of_living": (
            max_cost_of_living if max_cost_of_living is not None else current["max_cost_of_living"]
        ),
    }
    cache.set(_climate_budget_key(key), merged, CONVERSATION_TTL_SECONDS)
    return merged


def _profile_confirmed_key(key: str) -> str:
    return f"{key}:profile-confirmed"


def is_profile_confirmed(key: str) -> bool:
    """Has this conversation already been asked once to confirm its saved
    profile context? Kept as its own cache key, separate from the turn
    history, since it needs to work even for saved conversations that read
    their messages from Postgres instead of here."""
    return bool(cache.get(_profile_confirmed_key(key)))


def mark_profile_confirmed(key: str) -> None:
    """Mark the one-time profile confirmation as done, so we don't ask
    again on every message. Same TTL as the turn history - once the
    conversation goes stale, this resets with everything else."""
    cache.set(_profile_confirmed_key(key), True, CONVERSATION_TTL_SECONDS)
