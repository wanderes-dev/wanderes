import re
import uuid

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
    # The accumulated traveler state belongs to this same conversation, so
    # it has to live exactly as long as the history does. Only the
    # recommendation path (and the feedback exclusion write) ever rewrites
    # it, so without this a stretch of other turns - small talk, a visa
    # question, a saved trip - kept the history alive while the state's own
    # clock ran down underneath it.
    refresh_state_lifetime(key)


def refresh_state_lifetime(key: str) -> None:
    """Restart the clock on the accumulated state, on its owner record and -
    when the owner is a pending token - on the promotion record that vouches
    for it, so all of them live as long as the conversation does. The
    promotion record only counts while the owner is still that very token, so
    it must not age out before the owner does: an owner that's still there
    would quietly stop being honoured, and the conversation would be stuck
    stateless until the owner itself expired.

    touch() is a no-op for a key that isn't there, so this never invents
    state, ownership or a promotion for a conversation that has none - a
    promotion record that has already expired stays gone, and an owner left
    pending without one stays unhonoured."""
    cache.touch(_climate_budget_key(key), CONVERSATION_TTL_SECONDS)
    owner = cache.get(_state_owner_key(key))
    if owner is None:
        return
    cache.touch(_state_owner_key(key), CONVERSATION_TTL_SECONDS)
    if isinstance(owner, str) and owner.startswith(_PENDING_OWNER_PREFIX):
        cache.touch(_owner_promotion_key(key, owner), CONVERSATION_TTL_SECONDS)


def clear_history(key: str) -> None:
    """Wipe whatever context exists for this key - used when a traveler
    starts a fresh conversation, so it doesn't quietly inherit whatever
    was discussed last time under the same key. The state's owner goes with
    it: there's nothing left to own. The owner goes FIRST, like in any other
    change to the state (see update_climate_budget), so nobody is ever
    considered the owner of a state that's being torn down."""
    cache.delete(_state_owner_key(key))
    cache.delete(_climate_budget_key(key))
    cache.delete(key)


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
    # The specific destination the traveler has chosen to go to, as a
    # {"slug", "name", "country"} record (slug is None for a real place that
    # isn't in the catalog) - not the same thing as `country`, which is only
    # ever a constraint on discovery. Resolved once when it's set, so the
    # follow-ups that rely on it never have to re-resolve a name.
    "selected_destination": None,
    # What the traveler has said about the trip itself - start date, stay
    # length, who is going - as the record ai.trip_details defines. Only
    # what was actually stated; derived values (the check-out date) are
    # never stored.
    "trip_details": None,
}


def get_climate_budget(key: str) -> dict:
    """Accumulated traveler-state fields for this conversation - built up
    turn by turn by update_climate_budget() below, not re-derived from raw
    history. Named for the two fields it started with (min_temp_c/
    max_temp_c/max_cost_of_living); grew to cover trip_type/continent/
    country/excluded_place_names too once those turned out to need the
    exact same "isolated per-turn signal, accumulated across turns"
    treatment - see update_climate_budget's docstring. A state stored
    before a field existed simply reads as blank for it."""
    stored = cache.get(_climate_budget_key(key))
    if not stored:
        return dict(_NO_CLIMATE_BUDGET)
    return {**_NO_CLIMATE_BUDGET, **stored}


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


def _resolve_cross_turn_temperature_contradiction(traveler_state: dict, state_delta: dict) -> None:
    """A single message's own min_temp_c/max_temp_c can't contradict itself
    (ai.orchestration._validate_climate_budget drops both when it does),
    but merging across turns can produce a contradiction neither turn had
    on its own: "somewhere hot" persists as min_temp_c=28, then "actually
    somewhere cold" sets max_temp_c=15 without saying anything about
    min_temp_c - there's nothing for it to clear from its own point of
    view. Handing scoring that pair as-is would zero out every
    destination. The side THIS turn just stated wins; the other, merely
    carried forward from an earlier turn, is the stale one. Mutates
    traveler_state in place.

    Runs inside the merge itself, before anything is persisted or used, so
    the stored state and the state a request is built from can't differ."""
    min_temp_c = traveler_state["min_temp_c"]
    max_temp_c = traveler_state["max_temp_c"]
    if min_temp_c is None or max_temp_c is None or min_temp_c <= max_temp_c:
        return
    new_min = state_delta.get("min_temp_c")
    new_max = state_delta.get("max_temp_c")
    if new_max is not None and new_min is None:
        traveler_state["min_temp_c"] = None
    elif new_min is not None and new_max is None:
        traveler_state["max_temp_c"] = None
    else:
        # Both sides came from this same turn (a fresh contradiction) or
        # neither did (a stale pair that was already stored) - no single
        # side is more current than the other, so drop both.
        traveler_state["min_temp_c"] = None
        traveler_state["max_temp_c"] = None


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
    selected_destination: dict | None = None,
    selected_destination_cleared: bool = False,
    trip_details: dict | None = None,
    trip_details_cleared: bool = False,
    owner: int | str | None = None,
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
        selected_destination=selected_destination,
        selected_destination_cleared=selected_destination_cleared,
        trip_details=trip_details,
        trip_details_cleared=trip_details_cleared,
    )
    # `merged` is already fully resolved (see resolve_state_delta), so what
    # gets stored is exactly what's returned - and exactly what the caller
    # builds its request from.
    #
    # `owner` says whose state this now is (see "Who owns the accumulated
    # state" below); None means nobody that can prove it, which is the
    # default so a caller that forgets fails closed. The order is fixed:
    #
    #   invalidate the existing owner -> write the state -> stamp the new owner
    #
    # The owner is dropped first, for EVERY writer (whoever is writing, and
    # whether or not it will stamp itself afterwards): an old owner must never
    # be able to look valid while the state under it is being changed by
    # someone else. The new owner is stamped only once the state is written,
    # so ownership never points at state that isn't there yet.
    #
    # An unowned write has to END with no owner, so it drops the owner once
    # more after writing: between its first delete and its state write the
    # slot looks empty, and a claim (or another writer's stamp) landing in
    # that gap would otherwise go on to vouch for state it never saw. A
    # stamping writer doesn't need this - its own stamp replaces whatever
    # landed in the gap.
    cache.delete(_state_owner_key(key))
    cache.set(_climate_budget_key(key), merged, CONVERSATION_TTL_SECONDS)
    if owner is not None:
        cache.set(_state_owner_key(key), owner, CONVERSATION_TTL_SECONDS)
    else:
        cache.delete(_state_owner_key(key))
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
    selected_destination: dict | None = None,
    selected_destination_cleared: bool = False,
    trip_details: dict | None = None,
    trip_details_cleared: bool = False,
) -> dict:
    """The same SET/UNCHANGED/CLEAR merge update_climate_budget() persists,
    exposed standalone for a caller with no conv_key to accumulate into -
    a saved-conversation resume (ai.orchestration's history_override path)
    has no Redis session to read/write, so it resolves this turn's signal
    against blank state (dict(_NO_CLIMATE_BUDGET)) instead, getting back a
    plain trip_type/continent/country/excluded_place_names shape rather
    than the raw add/remove/cleared plumbing. current defaults to blank
    state when omitted, for a caller with nothing to merge against at all.

    The returned state is final: once the per-field merge has run, the
    min_temp_c/max_temp_c pair is reconciled against this turn's own
    temperature values, so a stored state is never one that scoring would
    have to repair."""
    current = current if current is not None else dict(_NO_CLIMATE_BUDGET)
    resolved = {
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
        "selected_destination": _merge_scalar(
            current.get("selected_destination"), selected_destination, selected_destination_cleared
        ),
        # The record arrives already merged field by field (ai.trip_details
        # applies the traveler's corrections to the stored record), so here
        # it is a whole-value SET like selected_destination.
        "trip_details": _merge_scalar(
            current.get("trip_details"), trip_details, trip_details_cleared
        ),
    }
    _resolve_cross_turn_temperature_contradiction(
        resolved, {"min_temp_c": min_temp_c, "max_temp_c": max_temp_c}
    )
    return resolved


# Who owns the accumulated state
#
# The accumulated state lives under the per-USER key, but a signed-in user
# can have several saved conversations (and several tabs) that each could
# believe it's theirs. A saved conversation continued via history_override
# may therefore only read or write that state once its ownership is proven;
# otherwise it runs stateless, exactly as it always did.
#
# The owner is recorded next to the state, under "<key>:state-owner": a
# SavedConversation id, or a "pending:<token>" for the first turn of a
# conversation that doesn't have an id yet (the id only exists after the
# reply has streamed and the turn has been saved). Every change to the state
# drops the existing owner first and only then, if the writer can prove who
# it is, stamps itself (an unowned writer drops the owner again at the end) -
# so an owner record is only ever trusted while nothing else has touched the
# state since.
#
# Django's cache has no compare-and-set and no multi-key transaction, so the
# protocol never replaces an owner it didn't just write. A pending token is
# turned into a real id by a separate promotion record (promote_state_owner),
# and an empty slot is claimed with a fresh pending-style token that only
# becomes authoritative once it has been re-verified (claim_empty_state_slot).
#
# What this cannot do is close the gap between a turn's final ownership check
# and the state operation that follows it (or, in general, stop two writers'
# multi-step sequences from interleaving): another same-user writer can in
# principle land in that sub-millisecond window, and the turn would then
# merge that writer's state into its own and stamp itself as the owner. That
# is a real (if very unlikely) way to cross-contaminate, NOT a fail-closed
# outcome; closing it needs a lock or Redis-specific atomic scripting, and
# neither is justified by any evidence that the race happens.
_PENDING_OWNER_PREFIX = "pending:"


def _state_owner_key(key: str) -> str:
    return f"{key}:state-owner"


def _owner_promotion_key(key: str, pending: str) -> str:
    return f"{key}:state-owner-promotion:{pending}"


def new_pending_owner() -> str:
    """A one-off owner token for a conversation that's about to be saved."""
    return f"{_PENDING_OWNER_PREFIX}{uuid.uuid4().hex}"


def get_state_owner(key: str) -> int | str | None:
    return cache.get(_state_owner_key(key))


def state_owned_by(key: str, conversation_id: int) -> bool:
    """Whether the state under `key` is provably this saved conversation's:
    the owner record is its id, or a pending token that was promoted to it
    and that nothing has replaced since."""
    owner = cache.get(_state_owner_key(key))
    if owner is None or isinstance(owner, bool):
        return False
    if isinstance(owner, int):
        return owner == conversation_id
    if isinstance(owner, str) and owner.startswith(_PENDING_OWNER_PREFIX):
        return cache.get(_owner_promotion_key(key, owner)) == conversation_id
    return False


def promote_state_owner(key: str, pending: str, conversation_id: int) -> bool:
    """Record that the conversation which has just been saved is the one
    that held `pending`.

    Django's cache has no compare-and-set, so "replace the pending owner
    with the id" would be a read followed by a write - and a writer that
    took the state in between would have its ownership overwritten.
    Promotion therefore never writes the owner record at all. It records,
    once (cache.add is atomic), which conversation the pending token turned
    out to be, and state_owned_by() honours that only while the owner record
    is still that very token. Anyone else having stamped or cleared the owner
    in the meantime leaves the promotion record unconsulted - the same result
    as a compare-and-set that failed. Returns whether this call recorded it."""
    if not pending.startswith(_PENDING_OWNER_PREFIX):
        return False
    promotion_key = _owner_promotion_key(key, pending)
    return bool(cache.add(promotion_key, conversation_id, CONVERSATION_TTL_SECONDS))


def claim_empty_state_slot(key: str, conversation_id: int) -> bool:
    """Take ownership of a slot that holds neither an owner nor any state -
    after an expiry, a restart, or a "New conversation" - so a saved
    conversation can start accumulating state from this turn on. Nothing is
    inherited and nothing is wiped: if there's any state at all, or anyone
    already owns the slot, this declines.

    The claim is a fresh, unique pending-style token put in the owner slot
    with cache.add, which is atomic, so two tabs racing for the same empty
    slot can't both win. A token in the owner slot means nothing yet: the
    state is checked again after winning, and only if the slot is still
    empty is the token promoted to this conversation (the same promotion
    record a saved conversation's first turn uses), which is what makes it
    authoritative - and the claim is reported only if the token is still the
    owner after that. If some writer slipped state in between the first look
    and the claim, the token is simply never promoted and never honoured.

    Nothing here ever deletes or overwrites an owner record or touches the
    state, so a claimant that loses - to another claimant, or to a writer - can't
    damage whoever won. A token that loses to a writer's state is left alone
    (the writer's own stamp or clear replaces it; otherwise it just expires),
    which keeps the slot unavailable, never wrongly available."""
    state_key = _climate_budget_key(key)
    owner_key = _state_owner_key(key)
    if cache.get(state_key) is not None or cache.get(owner_key) is not None:
        return False
    claim = new_pending_owner()
    if not cache.add(owner_key, claim, CONVERSATION_TTL_SECONDS):
        return False
    if cache.get(state_key) is not None:
        return False
    if not promote_state_owner(key, claim, conversation_id):
        return False
    # A writer can still have replaced or cleared the token between the
    # re-check and the promotion; only report a claim that holds right now.
    return state_owned_by(key, conversation_id)


def claim_state_for_conversation(key: str, conversation_id: int) -> bool:
    """May this saved conversation use the state under `key` this turn?
    Yes if it already owns it, or if the slot is empty and it can claim it;
    anything else (another owner, or state nobody can vouch for) is no."""
    return state_owned_by(key, conversation_id) or claim_empty_state_slot(key, conversation_id)


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
