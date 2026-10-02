"""Shared scaffolding for tests that drive stream_travel_recommendation()
through several turns with scripted model output."""

from django.core.cache import cache

from ai.provider.base import AIResponse
from integrations.climate.base import MonthlyClimateSummary
from travel.models import Destination

BASE_INTENT = {
    "message_type": "recommendation",
    "month": None,
    "min_temp_c": None,
    "max_temp_c": None,
    "max_cost_of_living": None,
    "trip_type": None,
    "continent": None,
    "country": None,
    "excluded_place_names": [],
    "selected_destination_name": None,
    "feedback_destination_name": None,
    "feedback_rating": None,
    "feedback_tags": [],
    "feedback_comment": None,
    "future_destination_name": None,
    "is_recall_request": False,
    "is_visa_or_entry_question": False,
    "visa_question_country": None,
    "visa_question_nationality": None,
    "is_booking_request": False,
    "is_video_request": False,
    "video_place_name": None,
    "is_activity_question": False,
    "activity_place_name": None,
    "is_accommodation_request": False,
    "accommodation_place_name": None,
    "accommodation_party_size": None,
}


def intent(**overrides) -> dict:
    return {**BASE_INTENT, **overrides}


class ScriptedProvider:
    """One scripted answer set per turn: turns[n] is a dict with an
    "intent" plus optional "climate_budget" and "state_clear" answers, and
    optionally "destination_resolution" / "freeform_place" for the calls that
    resolve a name the catalog lookup missed (unscripted, both answer "no").
    The combined intent call is always the first structured call of a turn,
    so it's what advances the turn counter. Records every call so a test can
    assert exactly how many model calls a turn made."""

    def __init__(self, turns, reply_text="A reply."):
        self.turns = turns
        self.reply_text = reply_text
        self.turn = -1
        self.structured_calls = []
        self.reply_calls = 0
        self.stream_calls = 0
        # Optional callable(schema_name), run at the start of every structured
        # call - lets a test make something else happen mid-turn, the way
        # another tab could while the model calls are in flight.
        self.before_call = None
        # The messages each combined-intent call was given, i.e. the history
        # the turn actually saw.
        self.intent_messages = []
        # The messages each streamed reply was generated from - what a test
        # reads to tell which kind of reply a turn took.
        self.stream_messages = []

    @property
    def total_calls(self) -> int:
        return len(self.structured_calls) + self.reply_calls + self.stream_calls

    def generate_structured_reply(
        self, messages, *, json_schema, max_tokens=None, temperature=None
    ):
        name = json_schema["name"]
        self.structured_calls.append(name)
        if self.before_call is not None:
            self.before_call(name)
        if name == "travel_message":
            self.turn += 1
            self.intent_messages.append(list(messages))
            return dict(self.turns[self.turn]["intent"])
        script = self.turns[self.turn]
        if name == "climate_budget_signal":
            return dict(script.get("climate_budget", {}))
        if name == "traveler_state_clear_signal":
            return dict(script.get("state_clear", {}))
        if name == "destination_resolution":
            return dict(script.get("destination_resolution", {}))
        if name == "freeform_place_resolution":
            return dict(script.get("freeform_place", {}))
        return {}

    def generate_reply(self, messages, *, max_tokens=None):
        self.reply_calls += 1
        return AIResponse(content="ok", model="stub", prompt_tokens=0, completion_tokens=0)

    def stream_reply(self, messages, *, max_tokens=None, temperature=None):
        self.stream_calls += 1
        self.stream_messages.append(list(messages))
        yield self.reply_text


class FixedClimateProvider:
    """Real weather isn't the point of these tests."""

    def get_monthly_climate(self, *, latitude, longitude, month, year=None):
        return MonthlyClimateSummary(2025, month, 28.0, 20.0, 5.0)

    def __bool__(self):
        return True


def make_destination(slug, **kwargs) -> Destination:
    defaults = dict(
        name=slug,
        country="Testland",
        latitude=10.0,
        longitude=10.0,
        trip_type="culture",
        cost_of_living=2,
        best_season="x",
        worst_season="x",
        short_description="x",
        points_of_interest=[],
    )
    defaults.update(kwargs)
    return Destination.objects.create(slug=slug, **defaults)


def remaining_ttl_seconds(key: str) -> int | None:
    """Seconds left on a cache key, read straight from Redis (Django's cache
    API doesn't expose it). None when the key is missing or never expires."""
    made_key = cache.make_and_validate_key(key)
    ttl = cache._cache.get_client(made_key, write=False).ttl(made_key)
    return None if ttl < 0 else ttl


class InterleavingCache:
    """Stands in for ai.memory.cache (patch "ai.memory.cache") and runs a
    callback right after a chosen cache operation, so a test can play out
    another writer's steps at an exact point inside someone else's protocol.
    Each hook fires once, and the callback's own cache calls go through the
    same wrapper (so its operations can be observed or hooked as well)."""

    def __init__(self, real):
        self._real = real
        self._hooks = []
        self.ops = []

    def after(self, op, key_suffix, callback):
        self._hooks.append([op, key_suffix, callback])

    def _ran(self, op, key):
        self.ops.append((op, key.rsplit(":", 1)[-1] if ":" in key else key))
        for hook in self._hooks:
            if hook[0] == op and key.endswith(hook[1]) and hook[2] is not None:
                callback, hook[2] = hook[2], None
                callback()

    def get(self, key, *args, **kwargs):
        value = self._real.get(key, *args, **kwargs)
        self._ran("get", key)
        return value

    def set(self, key, *args, **kwargs):
        result = self._real.set(key, *args, **kwargs)
        self._ran("set", key)
        return result

    def add(self, key, *args, **kwargs):
        result = self._real.add(key, *args, **kwargs)
        self._ran("add", key)
        return result

    def delete(self, key, *args, **kwargs):
        result = self._real.delete(key, *args, **kwargs)
        self._ran("delete", key)
        return result

    def touch(self, key, *args, **kwargs):
        result = self._real.touch(key, *args, **kwargs)
        self._ran("touch", key)
        return result

    def __getattr__(self, name):
        return getattr(self._real, name)


class StateWriteSpy:
    """Stands in for ai.memory.cache (patch "ai.memory.cache") and records
    every value written to a conversation's accumulated-state key, so a test
    can assert on what was ever stored, not just what's stored at the end."""

    def __init__(self, real):
        self._real = real
        self.state_writes = []

    def set(self, key, value, *args, **kwargs):
        if key.endswith(":climate-budget"):
            self.state_writes.append(dict(value))
        return self._real.set(key, value, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)

    def contradictory_writes(self):
        return [
            w
            for w in self.state_writes
            if w["min_temp_c"] is not None
            and w["max_temp_c"] is not None
            and w["min_temp_c"] > w["max_temp_c"]
        ]
