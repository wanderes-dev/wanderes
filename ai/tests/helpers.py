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
    "intent" plus optional "climate_budget" and "state_clear" answers. The
    combined intent call is always the first structured call of a turn, so
    it's what advances the turn counter. Records every call so a test can
    assert exactly how many model calls a turn made."""

    def __init__(self, turns):
        self.turns = turns
        self.turn = -1
        self.structured_calls = []
        self.reply_calls = 0
        self.stream_calls = 0

    @property
    def total_calls(self) -> int:
        return len(self.structured_calls) + self.reply_calls + self.stream_calls

    def generate_structured_reply(
        self, messages, *, json_schema, max_tokens=None, temperature=None
    ):
        name = json_schema["name"]
        self.structured_calls.append(name)
        if name == "travel_message":
            self.turn += 1
            return dict(self.turns[self.turn]["intent"])
        script = self.turns[self.turn]
        if name == "climate_budget_signal":
            return dict(script.get("climate_budget", {}))
        if name == "traveler_state_clear_signal":
            return dict(script.get("state_clear", {}))
        return {}

    def generate_reply(self, messages, *, max_tokens=None):
        self.reply_calls += 1
        return AIResponse(content="ok", model="stub", prompt_tokens=0, completion_tokens=0)

    def stream_reply(self, messages, *, max_tokens=None, temperature=None):
        self.stream_calls += 1
        yield "A reply."


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
