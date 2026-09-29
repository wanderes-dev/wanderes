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
# something WE said. Prompt tweaks didn't hold up, so we strip these
# figures before that one call ever sees them (ai.orchestration.
# _sanitized_history_messages) - NOT at storage time. Sanitizing here used
# to mean every history consumer got the redacted version, which broke
# genuine recall ("what beaches did you suggest?") - the real figures were
# gone before they were ever saved, so there was nothing left to recall,
# and the model just echoed the literal "[cost]" placeholder back.
_TEMPERATURE_PATTERN = re.compile(
    r"-?\d{1,3}(?:[.,]\d+)?\s*(?:-\s*-?\d{1,3}(?:[.,]\d+)?)?\s*°\s*C", re.IGNORECASE
)
_COST_TIER_PATTERN = re.compile(r"\b[1-5]\s*/\s*5\b")


def sanitize_reply_for_context(assistant_reply: str) -> str:
    """Strip temperature/cost-tier figures (e.g. "31°C", "4/5") from an
    assistant reply before it's fed to intent extraction as history. Never
    applied to what's streamed to the traveler, what gets persisted, or
    the raw text used for a saved conversation's title - see the note
    above. Only covers the patterns known to cause contamination, not a
    general-purpose scrubber."""
    sanitized = _TEMPERATURE_PATTERN.sub("[temp]", assistant_reply)
    return _COST_TIER_PATTERN.sub("[cost]", sanitized)


def append_turn(key: str, *, user_message: str, assistant_reply: str) -> None:
    """Save one exchange, trim to MAX_HISTORY_MESSAGES, refresh the TTL.
    Called for every handled message no matter which branch produced the
    reply. Stores the reply exactly as sent to the traveler - see
    sanitize_reply_for_context's docstring for why this doesn't sanitize
    it first."""
    history = get_history(key)
    history.append({"role": "user", "content": user_message})
    history.append({"role": "assistant", "content": assistant_reply})
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


_NO_CLIMATE_BUDGET = {
    "min_temp_c": None,
    "max_temp_c": None,
    "max_cost_of_living": None,
    "trip_type": None,
    "continent": None,
    "country": None,
    "excluded_place_names": [],
}


def get_climate_budget(key: str) -> dict:
    """Accumulated traveler-state fields for this conversation - built up
    turn by turn by update_climate_budget() below, not re-derived from raw
    history. Named for the two fields it started with (min_temp_c/
    max_temp_c/max_cost_of_living); grew to cover trip_type/continent/
    country/excluded_place_names too once those turned out to need the
    exact same "isolated per-turn signal, accumulated across turns"
    treatment - see update_climate_budget's docstring."""
    return cache.get(_climate_budget_key(key)) or dict(_NO_CLIMATE_BUDGET)


def _merge_scalar(current, new_value, cleared: bool):
    """One field's SET/UNCHANGED/CLEAR merge: an explicit new value always
    wins, an explicit clear (only when no new value came with it) resets
    to null, and otherwise the accumulated value carries forward
    untouched. A value and its clear flag both firing in the same turn
    shouldn't happen if the extraction prompt is doing its job, but if it
    ever does, treating that as "the user gave a value" is the safer
    read than silently dropping it."""
    if new_value is not None:
        return new_value
    if cleared:
        return None
    return current


def _merge_excluded_place_names(current: list, *, add, remove, cleared: bool) -> list:
    """Exclusions are a collection, not a scalar - "not Rome" adds one,
    "actually Rome's fine" removes it, and "forget my exclusions" clears
    the lot. Case-insensitive matching so "prague"/"Prague" don't end up
    as two entries or fail to cancel each other out."""
    names = [] if cleared else list(current)
    if remove:
        remove_lower = {name.strip().lower() for name in remove if name.strip()}
        names = [name for name in names if name.strip().lower() not in remove_lower]
    if add:
        seen_lower = {name.strip().lower() for name in names}
        for name in add:
            lowered = name.strip().lower()
            if lowered and lowered not in seen_lower:
                names.append(name)
                seen_lower.add(lowered)
    return names


def update_climate_budget(
    key: str,
    *,
    min_temp_c: float | None = None,
    min_temp_c_cleared: bool = False,
    max_temp_c: float | None = None,
    max_temp_c_cleared: bool = False,
    max_cost_of_living: int | None = None,
    max_cost_of_living_cleared: bool = False,
    trip_type: str | None = None,
    trip_type_cleared: bool = False,
    continent: str | None = None,
    continent_cleared: bool = False,
    country: str | None = None,
    country_cleared: bool = False,
    excluded_place_names_add: list[str] | None = None,
    excluded_place_names_remove: list[str] | None = None,
    excluded_place_names_cleared: bool = False,
) -> dict:
    """Merge this turn's (history-free) traveler-state signal into what's
    already accumulated. Each scalar field only changes when this call
    passes an explicit new value or an explicit clear for it - otherwise
    the older value sticks, which is what lets "praia" then "orçamento
    baixo" still combine across turns even though each extraction only
    ever sees one message at a time.

    This started out covering just min_temp_c/max_temp_c/
    max_cost_of_living, because letting intent extraction re-derive them
    from full history every turn wasn't safe - even with numbers stripped
    from old replies, the model could still infer warmth from a
    destination name alone (Phuket, say). trip_type/continent/country/
    excluded_place_names had the opposite problem: extracted fresh every
    turn with no accumulator at all, a message that didn't restate one of
    them silently dropped it (the dominant LOST_CONTEXT failure in the
    Cycle 2 conversation evaluation). Both problems are really the same
    one - "was this field mentioned, corrected, or explicitly dropped
    THIS turn" can't be answered by looking at accumulated history, only
    by asking about the current message in isolation - so this accumulator
    now covers all seven fields the same way rather than growing a second,
    differently-shaped mechanism next to it.

    The three original fields intentionally have no clear-flag equivalent
    upstream (ai.orchestration's CLIMATE_BUDGET_SYSTEM_PROMPT can already
    ask for one from the same isolated message; see the *_cleared kwargs
    below) - a bare null from a failed extraction and an explicit "price
    doesn't matter anymore" used to be indistinguishable, which is exactly
    the bug the Cycle 2 evaluation surfaced for contradiction-resolution
    scenarios."""
    merged = resolve_state_delta(
        get_climate_budget(key),
        min_temp_c=min_temp_c,
        min_temp_c_cleared=min_temp_c_cleared,
        max_temp_c=max_temp_c,
        max_temp_c_cleared=max_temp_c_cleared,
        max_cost_of_living=max_cost_of_living,
        max_cost_of_living_cleared=max_cost_of_living_cleared,
        trip_type=trip_type,
        trip_type_cleared=trip_type_cleared,
        continent=continent,
        continent_cleared=continent_cleared,
        country=country,
        country_cleared=country_cleared,
        excluded_place_names_add=excluded_place_names_add,
        excluded_place_names_remove=excluded_place_names_remove,
        excluded_place_names_cleared=excluded_place_names_cleared,
    )
    cache.set(_climate_budget_key(key), merged, CONVERSATION_TTL_SECONDS)
    return merged


def resolve_state_delta(
    current: dict | None = None,
    *,
    min_temp_c: float | None = None,
    min_temp_c_cleared: bool = False,
    max_temp_c: float | None = None,
    max_temp_c_cleared: bool = False,
    max_cost_of_living: int | None = None,
    max_cost_of_living_cleared: bool = False,
    trip_type: str | None = None,
    trip_type_cleared: bool = False,
    continent: str | None = None,
    continent_cleared: bool = False,
    country: str | None = None,
    country_cleared: bool = False,
    excluded_place_names_add: list[str] | None = None,
    excluded_place_names_remove: list[str] | None = None,
    excluded_place_names_cleared: bool = False,
) -> dict:
    """The same SET/UNCHANGED/CLEAR merge update_climate_budget() persists,
    exposed standalone for a caller with no conv_key to accumulate into -
    a saved-conversation resume (ai.orchestration's history_override path)
    has no Redis session to read/write, so it resolves this turn's signal
    against blank state (dict(_NO_CLIMATE_BUDGET)) instead, getting back a
    plain trip_type/continent/country/excluded_place_names shape rather
    than the raw add/remove/cleared plumbing. current defaults to blank
    state when omitted, for a caller with nothing to merge against at all."""
    current = current if current is not None else dict(_NO_CLIMATE_BUDGET)
    return {
        "min_temp_c": _merge_scalar(current["min_temp_c"], min_temp_c, min_temp_c_cleared),
        "max_temp_c": _merge_scalar(current["max_temp_c"], max_temp_c, max_temp_c_cleared),
        "max_cost_of_living": _merge_scalar(
            current["max_cost_of_living"], max_cost_of_living, max_cost_of_living_cleared
        ),
        "trip_type": _merge_scalar(current["trip_type"], trip_type, trip_type_cleared),
        "continent": _merge_scalar(current["continent"], continent, continent_cleared),
        "country": _merge_scalar(current["country"], country, country_cleared),
        "excluded_place_names": _merge_excluded_place_names(
            current["excluded_place_names"],
            add=excluded_place_names_add,
            remove=excluded_place_names_remove,
            cleared=excluded_place_names_cleared,
        ),
    }


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
