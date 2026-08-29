from django.test import TestCase

from ai.orchestration import (
    FALLBACK_REPLY,
    NO_MATCHES_REPLY,
    OFF_TOPIC_REPLY,
    get_travel_recommendation,
    stream_travel_recommendation,
)
from ai.provider.base import AIProviderError
from integrations.climate.base import ClimateProviderError, MonthlyClimateSummary
from travel.models import Destination


class StubClimateProvider:
    def __init__(self, climate_by_coords):
        self._climate_by_coords = climate_by_coords

    def get_monthly_climate(self, *, latitude, longitude, month, year=None):
        key = (round(float(latitude), 2), round(float(longitude), 2))
        if key not in self._climate_by_coords:
            raise ClimateProviderError(f"no stub data for {key}")
        return self._climate_by_coords[key]


class StubAIProvider:
    def __init__(self, *, structured_response, reply_text="Here's my recommendation."):
        self.structured_response = structured_response
        self.reply_text = reply_text
        self.stream_reply_calls = []
        self.generate_structured_reply_calls = []

    def generate_structured_reply(self, messages, *, json_schema, max_tokens=None):
        self.generate_structured_reply_calls.append(messages)
        return self.structured_response

    def stream_reply(self, messages, *, max_tokens=None):
        self.stream_reply_calls.append(messages)
        for word in self.reply_text.split(" "):
            yield word + " "


class FailingAIProvider:
    def generate_structured_reply(self, messages, *, json_schema, max_tokens=None):
        raise AIProviderError("boom")

    def stream_reply(self, messages, *, max_tokens=None):
        raise AIProviderError("boom")


def _make_destination(slug, *, lat, lon, trip_type="beach", cost_of_living=1):
    return Destination.objects.create(
        slug=slug,
        name=slug,
        country="Testland",
        latitude=lat,
        longitude=lon,
        trip_type=trip_type,
        cost_of_living=cost_of_living,
        best_season="Jan-Dec",
        worst_season="None",
        short_description="A test destination.",
        points_of_interest=[],
    )


def _intent(
    *,
    is_travel_request=True,
    needs_clarification=False,
    clarification_question=None,
    month=None,
    min_temp_c=None,
    max_cost_of_living=None,
):
    return {
        "is_travel_request": is_travel_request,
        "needs_clarification": needs_clarification,
        "clarification_question": clarification_question,
        "month": month,
        "min_temp_c": min_temp_c,
        "max_cost_of_living": max_cost_of_living,
    }


class GetTravelRecommendationTests(TestCase):
    """Tests the non-streaming convenience wrapper (joined chunks)."""

    def setUp(self):
        self.destination = _make_destination("warm-cheap", lat=10.0, lon=10.0)
        self.climate = StubClimateProvider(
            {(10.0, 10.0): MonthlyClimateSummary(2025, 10, 28.0, 20.0, 5.0)}
        )

    def test_off_topic_message_returns_canned_reply_without_calling_ai_again(self):
        ai_provider = StubAIProvider(structured_response=_intent(is_travel_request=False))

        result = get_travel_recommendation(
            "what's the capital of France?", ai_provider=ai_provider, climate_provider=self.climate
        )

        self.assertEqual(result.reply, OFF_TOPIC_REPLY)
        self.assertEqual(result.recommendations, [])
        self.assertEqual(ai_provider.stream_reply_calls, [])

    def test_missing_month_asks_for_clarification(self):
        ai_provider = StubAIProvider(
            structured_response=_intent(
                needs_clarification=True, clarification_question="Which month?"
            )
        )

        result = get_travel_recommendation(
            "somewhere warm", ai_provider=ai_provider, climate_provider=self.climate
        )

        self.assertTrue(result.needs_clarification)
        self.assertEqual(result.reply, "Which month?")
        self.assertEqual(result.recommendations, [])

    def test_valid_request_returns_scored_recommendations_and_explanation(self):
        ai_provider = StubAIProvider(
            structured_response=_intent(month=10, min_temp_c=20.0, max_cost_of_living=3),
            reply_text="Try the warm, cheap destination!",
        )

        result = get_travel_recommendation(
            "somewhere warm in October, not too expensive",
            ai_provider=ai_provider,
            climate_provider=self.climate,
        )

        self.assertEqual(result.reply, "Try the warm, cheap destination! ")
        self.assertEqual(len(result.recommendations), 1)
        self.assertEqual(result.recommendations[0].destination.slug, "warm-cheap")
        self.assertEqual(len(ai_provider.stream_reply_calls), 1)

    def test_no_matches_skips_the_explanation_call(self):
        ai_provider = StubAIProvider(structured_response=_intent(month=10, min_temp_c=100.0))

        result = get_travel_recommendation(
            "somewhere impossibly hot", ai_provider=ai_provider, climate_provider=self.climate
        )

        self.assertEqual(result.reply, NO_MATCHES_REPLY)
        self.assertEqual(result.recommendations, [])
        self.assertEqual(ai_provider.stream_reply_calls, [])

    def test_invalid_month_from_ai_triggers_clarification(self):
        ai_provider = StubAIProvider(structured_response=_intent(month=42))

        result = get_travel_recommendation(
            "somewhere nice sometime", ai_provider=ai_provider, climate_provider=self.climate
        )

        self.assertTrue(result.needs_clarification)

    def test_ai_provider_error_returns_fallback_reply(self):
        result = get_travel_recommendation(
            "somewhere warm in October",
            ai_provider=FailingAIProvider(),
            climate_provider=self.climate,
        )

        self.assertEqual(result.reply, FALLBACK_REPLY)
        self.assertEqual(result.recommendations, [])


class StreamTravelRecommendationTests(TestCase):
    """Tests the streaming pipeline directly - the actual chunk-by-chunk behavior."""

    def setUp(self):
        self.destination = _make_destination("warm-cheap", lat=10.0, lon=10.0)
        self.climate = StubClimateProvider(
            {(10.0, 10.0): MonthlyClimateSummary(2025, 10, 28.0, 20.0, 5.0)}
        )

    def test_valid_request_yields_multiple_chunks(self):
        ai_provider = StubAIProvider(
            structured_response=_intent(month=10, min_temp_c=20.0),
            reply_text="Try the warm cheap destination",
        )

        result = stream_travel_recommendation(
            "somewhere warm in October", ai_provider=ai_provider, climate_provider=self.climate
        )
        chunks = list(result.reply_chunks)

        self.assertGreater(len(chunks), 1)
        self.assertEqual("".join(chunks), "Try the warm cheap destination ")
        self.assertEqual(len(result.recommendations), 1)

    def test_mid_stream_failure_appends_fallback_chunk(self):
        class MidStreamFailingProvider:
            def generate_structured_reply(self, messages, *, json_schema, max_tokens=None):
                return _intent(month=10, min_temp_c=20.0)

            def stream_reply(self, messages, *, max_tokens=None):
                yield "Partial reply... "
                raise AIProviderError("connection dropped")

        result = stream_travel_recommendation(
            "somewhere warm in October",
            ai_provider=MidStreamFailingProvider(),
            climate_provider=self.climate,
        )
        chunks = list(result.reply_chunks)

        self.assertEqual(chunks, ["Partial reply... ", FALLBACK_REPLY])

    def test_off_topic_yields_single_canned_chunk(self):
        ai_provider = StubAIProvider(structured_response=_intent(is_travel_request=False))

        result = stream_travel_recommendation(
            "what's the capital of France?", ai_provider=ai_provider, climate_provider=self.climate
        )

        self.assertEqual(list(result.reply_chunks), [OFF_TOPIC_REPLY])
        self.assertEqual(ai_provider.stream_reply_calls, [])
