from django.test import TestCase

from ai import memory
from ai.orchestration import (
    FALLBACK_REPLY,
    NEEDS_LOGIN_REPLY,
    OFF_TOPIC_REPLY,
    get_travel_recommendation,
    stream_travel_recommendation,
)
from ai.provider.base import AIProviderError
from analytics.models import Event
from integrations.climate.base import ClimateProviderError, MonthlyClimateSummary
from travel.models import Destination
from trips.models import Feedback, TravelHistoryEntry, Trip
from users.models import User


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
    message_type="recommendation",
    needs_clarification=False,
    clarification_question=None,
    month=None,
    min_temp_c=None,
    max_cost_of_living=None,
    trip_type=None,
    excluded_place_names=None,
    feedback_destination_name=None,
    feedback_rating=None,
    feedback_tags=None,
    feedback_comment=None,
    future_destination_name=None,
):
    return {
        "message_type": message_type,
        "needs_clarification": needs_clarification,
        "clarification_question": clarification_question,
        "month": month,
        "min_temp_c": min_temp_c,
        "max_cost_of_living": max_cost_of_living,
        "trip_type": trip_type,
        "excluded_place_names": excluded_place_names or [],
        "feedback_destination_name": feedback_destination_name,
        "feedback_rating": feedback_rating,
        "feedback_tags": feedback_tags or [],
        "feedback_comment": feedback_comment,
        "future_destination_name": future_destination_name,
    }


class GetTravelRecommendationTests(TestCase):
    """Tests the non-streaming convenience wrapper (joined chunks)."""

    def setUp(self):
        self.destination = _make_destination("warm-cheap", lat=10.0, lon=10.0)
        self.climate = StubClimateProvider(
            {(10.0, 10.0): MonthlyClimateSummary(2025, 10, 28.0, 20.0, 5.0)}
        )

    def test_off_topic_message_returns_canned_reply_without_calling_ai_again(self):
        ai_provider = StubAIProvider(structured_response=_intent(message_type="off_topic"))

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

    def test_no_matches_asks_ai_to_help_instead_of_a_dead_end_reply(self):
        # Per the Phase 11 recommendation philosophy and a direct user
        # request: a hard-constraint dead end should not be a canned
        # message - the AI should try to help from its own knowledge, or
        # ask a genuine clarifying question, whichever fits.
        ai_provider = StubAIProvider(
            structured_response=_intent(month=10, min_temp_c=100.0),
            reply_text="Here's a real suggestion from general knowledge.",
        )

        result = get_travel_recommendation(
            "somewhere impossibly hot", ai_provider=ai_provider, climate_provider=self.climate
        )

        self.assertEqual(result.reply, "Here's a real suggestion from general knowledge. ")
        self.assertEqual(result.recommendations, [])
        self.assertEqual(len(ai_provider.stream_reply_calls), 1)

    def test_invalid_month_from_ai_triggers_clarification(self):
        ai_provider = StubAIProvider(structured_response=_intent(month=42))

        result = get_travel_recommendation(
            "somewhere nice sometime", ai_provider=ai_provider, climate_provider=self.climate
        )

        self.assertTrue(result.needs_clarification)

    def test_month_present_never_needs_clarification_even_if_ai_says_so(self):
        # Regression test: reported live - the model kept asking about
        # trip_type (an optional field) as if it were required, looping
        # forever even after the user answered twice. Month is the only
        # thing RecommendationRequest actually requires, so once it's
        # present the app must proceed regardless of what needs_clarification
        # the model itself set.
        ai_provider = StubAIProvider(
            structured_response=_intent(
                month=10,
                needs_clarification=True,
                clarification_question="What type of destination are you interested in?",
            ),
            reply_text="Try the warm, cheap destination!",
        )

        result = get_travel_recommendation(
            "low cost trip and a warm place",
            ai_provider=ai_provider,
            climate_provider=self.climate,
        )

        self.assertFalse(result.needs_clarification)
        self.assertEqual(len(result.recommendations), 1)

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
        ai_provider = StubAIProvider(structured_response=_intent(message_type="off_topic"))

        result = stream_travel_recommendation(
            "what's the capital of France?", ai_provider=ai_provider, climate_provider=self.climate
        )

        self.assertEqual(list(result.reply_chunks), [OFF_TOPIC_REPLY])
        self.assertEqual(ai_provider.stream_reply_calls, [])


class TripTypeAndExclusionTests(TestCase):
    """Phase 11 found that trip_type and exclusions had no effect at all -
    these lock in the fix."""

    def setUp(self):
        self.beach_destination = _make_destination(
            "warm-beach", lat=10.0, lon=10.0, trip_type="beach"
        )
        self.city_destination = _make_destination(
            "warm-city", lat=11.0, lon=11.0, trip_type="city"
        )
        self.climate = StubClimateProvider(
            {
                (10.0, 10.0): MonthlyClimateSummary(2025, 10, 28.0, 20.0, 5.0),
                (11.0, 11.0): MonthlyClimateSummary(2025, 10, 27.0, 19.0, 5.0),
            }
        )

    def test_trip_type_filters_out_non_matching_destinations(self):
        ai_provider = StubAIProvider(
            structured_response=_intent(month=10, min_temp_c=20.0, trip_type="beach")
        )

        result = get_travel_recommendation(
            "I want a beach vacation in October",
            ai_provider=ai_provider,
            climate_provider=self.climate,
        )

        slugs = {r.destination.slug for r in result.recommendations}
        self.assertEqual(slugs, {"warm-beach"})

    def test_excluded_place_name_removes_matching_destination(self):
        ai_provider = StubAIProvider(
            structured_response=_intent(
                month=10, min_temp_c=20.0, excluded_place_names=["warm-city"]
            )
        )

        result = get_travel_recommendation(
            "somewhere warm in October, not warm-city though",
            ai_provider=ai_provider,
            climate_provider=self.climate,
        )

        slugs = {r.destination.slug for r in result.recommendations}
        self.assertEqual(slugs, {"warm-beach"})

    def test_excluded_place_name_matches_by_country(self):
        ai_provider = StubAIProvider(
            structured_response=_intent(
                month=10, min_temp_c=20.0, excluded_place_names=["Testland"]
            )
        )

        result = get_travel_recommendation(
            "somewhere warm in October, not Testland",
            ai_provider=ai_provider,
            climate_provider=self.climate,
        )

        self.assertEqual(result.recommendations, [])


class UnhandledRequestLoggingTests(TestCase):
    """Per the 2026-08-29 recommendation-philosophy decision: unplanned
    requests fall to the AI's own judgment, but that fact gets logged for
    future review rather than passing silently."""

    def setUp(self):
        self.destination = _make_destination("warm-cheap", lat=10.0, lon=10.0)
        self.climate = StubClimateProvider(
            {(10.0, 10.0): MonthlyClimateSummary(2025, 10, 28.0, 20.0, 5.0)}
        )

    def test_logs_when_no_deterministic_constraints_extracted(self):
        ai_provider = StubAIProvider(structured_response=_intent(month=6))

        with self.assertLogs("ai.orchestration", level="INFO") as logs:
            get_travel_recommendation(
                "a romantic getaway in June", ai_provider=ai_provider, climate_provider=self.climate
            )

        self.assertTrue(any("relying on AI judgment" in message for message in logs.output))

    def test_logs_when_no_destinations_match(self):
        ai_provider = StubAIProvider(structured_response=_intent(month=10, min_temp_c=100.0))

        with self.assertLogs("ai.orchestration", level="INFO") as logs:
            get_travel_recommendation(
                "somewhere impossibly hot", ai_provider=ai_provider, climate_provider=self.climate
            )

        self.assertTrue(any("No destinations matched" in message for message in logs.output))

    def test_logs_warning_on_provider_failure(self):
        with self.assertLogs("ai.orchestration", level="WARNING") as logs:
            get_travel_recommendation(
                "somewhere warm in October",
                ai_provider=FailingAIProvider(),
                climate_provider=self.climate,
            )

        self.assertTrue(any("AI provider failure" in message for message in logs.output))


class ConversationalFeedbackAndFutureIntentTests(TestCase):
    """The AI must be able to receive feedback and register a past visit,
    or a stated future travel intention, directly from the chat - no
    separate page needed (2026-08-29 requirement)."""

    def setUp(self):
        self.user = User.objects.create_user(email="traveler@example.com", password="testpass123")
        self.destination = _make_destination("lisbon", lat=38.72, lon=-9.14, trip_type="city")
        self.climate = StubClimateProvider({})

    def test_feedback_with_rating_creates_feedback_and_history(self):
        ai_provider = StubAIProvider(
            structured_response=_intent(
                message_type="feedback",
                feedback_destination_name="lisbon",
                feedback_rating=8,
                feedback_tags=["excellent_food", "too_crowded"],
                feedback_comment="Loved the food.",
            )
        )

        result = get_travel_recommendation(
            "I went to Lisbon, it was amazing, 8/10, great food but too crowded",
            user=self.user,
            ai_provider=ai_provider,
            climate_provider=self.climate,
        )

        feedback = Feedback.objects.get(user=self.user, destination=self.destination)
        self.assertEqual(feedback.rating, 8)
        self.assertEqual(feedback.tags, ["excellent_food", "too_crowded"])
        self.assertTrue(
            TravelHistoryEntry.objects.filter(user=self.user, destination=self.destination).exists()
        )
        self.assertIn("lisbon", result.reply)
        self.assertEqual(ai_provider.stream_reply_calls, [])
        self.assertTrue(
            Event.objects.filter(
                user=self.user, event_type="feedback_submitted", metadata__source="chat"
            ).exists()
        )

    def test_feedback_without_rating_does_not_record_feedback_submitted(self):
        ai_provider = StubAIProvider(
            structured_response=_intent(
                message_type="feedback", feedback_destination_name="lisbon"
            )
        )

        get_travel_recommendation(
            "I visited Lisbon last year",
            user=self.user,
            ai_provider=ai_provider,
            climate_provider=self.climate,
        )

        self.assertFalse(Event.objects.filter(event_type="feedback_submitted").exists())

    def test_feedback_without_rating_only_registers_history(self):
        ai_provider = StubAIProvider(
            structured_response=_intent(
                message_type="feedback", feedback_destination_name="lisbon"
            )
        )

        result = get_travel_recommendation(
            "I visited Lisbon last year",
            user=self.user,
            ai_provider=ai_provider,
            climate_provider=self.climate,
        )

        self.assertTrue(
            TravelHistoryEntry.objects.filter(user=self.user, destination=self.destination).exists()
        )
        self.assertFalse(Feedback.objects.filter(user=self.user).exists())
        self.assertIn("lisbon", result.reply)

    def test_resubmitting_feedback_updates_rather_than_duplicates(self):
        ai_provider = StubAIProvider(
            structured_response=_intent(
                message_type="feedback", feedback_destination_name="lisbon", feedback_rating=5
            )
        )
        get_travel_recommendation(
            "Lisbon was ok, 5/10",
            user=self.user,
            ai_provider=ai_provider,
            climate_provider=self.climate,
        )

        ai_provider2 = StubAIProvider(
            structured_response=_intent(
                message_type="feedback", feedback_destination_name="lisbon", feedback_rating=9
            )
        )
        get_travel_recommendation(
            "Actually Lisbon was amazing, 9/10",
            user=self.user,
            ai_provider=ai_provider2,
            climate_provider=self.climate,
        )

        self.assertEqual(Feedback.objects.filter(user=self.user).count(), 1)
        self.assertEqual(Feedback.objects.get(user=self.user).rating, 9)

    def test_feedback_requires_login(self):
        ai_provider = StubAIProvider(
            structured_response=_intent(
                message_type="feedback", feedback_destination_name="lisbon", feedback_rating=8
            )
        )

        result = get_travel_recommendation(
            "Lisbon was great, 8/10",
            user=None,
            ai_provider=ai_provider,
            climate_provider=self.climate,
        )

        self.assertEqual(result.reply, NEEDS_LOGIN_REPLY)
        self.assertFalse(Feedback.objects.exists())

    def test_feedback_without_destination_asks_instead_of_requiring_login(self):
        # Regression test: an anonymous user must never hit a login wall
        # before the app even knows there's a real destination to save -
        # otherwise a misclassified message (e.g. a bare month/timing
        # answer the model mistook for feedback) dead-ends the chat.
        ai_provider = StubAIProvider(
            structured_response=_intent(message_type="feedback")
        )

        result = get_travel_recommendation(
            "someday between september and october",
            user=None,
            ai_provider=ai_provider,
            climate_provider=self.climate,
        )

        self.assertNotEqual(result.reply, NEEDS_LOGIN_REPLY)
        self.assertIn("which destination", result.reply)

    def test_future_intent_creates_planned_trip(self):
        ai_provider = StubAIProvider(
            structured_response=_intent(
                message_type="future_intent", future_destination_name="lisbon"
            )
        )

        result = get_travel_recommendation(
            "I want to go to Lisbon someday",
            user=self.user,
            ai_provider=ai_provider,
            climate_provider=self.climate,
        )

        trip = Trip.objects.get(user=self.user, destination=self.destination)
        self.assertEqual(trip.status, "planned")
        self.assertIn("lisbon", result.reply)
        self.assertTrue(
            Event.objects.filter(
                user=self.user, event_type="trip_created", metadata__source="chat"
            ).exists()
        )

    def test_future_intent_resubmission_does_not_duplicate_trip_created_event(self):
        ai_provider = StubAIProvider(
            structured_response=_intent(
                message_type="future_intent", future_destination_name="lisbon"
            )
        )

        get_travel_recommendation(
            "I want to go to Lisbon someday",
            user=self.user,
            ai_provider=ai_provider,
            climate_provider=self.climate,
        )
        get_travel_recommendation(
            "I still want to go to Lisbon someday",
            user=self.user,
            ai_provider=ai_provider,
            climate_provider=self.climate,
        )

        self.assertEqual(
            Event.objects.filter(user=self.user, event_type="trip_created").count(), 1
        )

    def test_future_intent_requires_login(self):
        ai_provider = StubAIProvider(
            structured_response=_intent(
                message_type="future_intent", future_destination_name="lisbon"
            )
        )

        result = get_travel_recommendation(
            "I want to go to Lisbon someday",
            user=None,
            ai_provider=ai_provider,
            climate_provider=self.climate,
        )

        self.assertEqual(result.reply, NEEDS_LOGIN_REPLY)
        self.assertFalse(Trip.objects.exists())

    def test_future_intent_without_destination_asks_instead_of_requiring_login(self):
        # Regression test: reported live - "someday between september and
        # october" (a month-only reply, no destination at all) was
        # misclassified as future_intent and hard-blocked an anonymous
        # user behind NEEDS_LOGIN_REPLY, killing the conversation. There is
        # nothing to save without a destination, so there's nothing to
        # gate on login for either.
        ai_provider = StubAIProvider(structured_response=_intent(message_type="future_intent"))

        result = get_travel_recommendation(
            "someday between september and october",
            user=None,
            ai_provider=ai_provider,
            climate_provider=self.climate,
        )

        self.assertNotEqual(result.reply, NEEDS_LOGIN_REPLY)
        self.assertIn("which destination", result.reply)

    def test_unrecognized_destination_in_feedback_does_not_crash(self):
        ai_provider = StubAIProvider(
            structured_response=_intent(
                message_type="feedback", feedback_destination_name="Nowhereland", feedback_rating=7
            )
        )

        result = get_travel_recommendation(
            "Nowhereland was great, 7/10",
            user=self.user,
            ai_provider=ai_provider,
            climate_provider=self.climate,
        )

        self.assertFalse(Feedback.objects.exists())
        self.assertIn("Nowhereland", result.reply)


class ConversationMemoryTests(TestCase):
    """Conversation memory (ai.memory, added 2026-08-30): prior turns should
    reach the intent extraction call so a short follow-up reply can be
    understood in context, per the real conversation that surfaced this -
    an anonymous user answering "what month?" with only a month, which is
    meaningless taken in isolation but is exactly the missing piece once
    the prior turn is visible."""

    def setUp(self):
        self.destination = _make_destination("warm-cheap", lat=10.0, lon=10.0)
        self.climate = StubClimateProvider(
            {(10.0, 10.0): MonthlyClimateSummary(2025, 10, 28.0, 20.0, 5.0)}
        )

    def test_first_message_sends_no_history(self):
        ai_provider = StubAIProvider(
            structured_response=_intent(message_type="off_topic")
        )

        get_travel_recommendation(
            "what's the capital of France?",
            session_key="session-1",
            ai_provider=ai_provider,
            climate_provider=self.climate,
        )

        sent_messages = ai_provider.generate_structured_reply_calls[0]
        # Just the system prompt + the current message - no prior turns yet.
        self.assertEqual(len(sent_messages), 2)

    def test_second_message_includes_prior_turn_in_history(self):
        first_provider = StubAIProvider(
            structured_response=_intent(
                message_type="recommendation", needs_clarification=True,
                clarification_question="What month are you planning to travel?",
            )
        )
        get_travel_recommendation(
            "what do you suggest for a destination?",
            session_key="session-2",
            ai_provider=first_provider,
            climate_provider=self.climate,
        )

        second_provider = StubAIProvider(
            structured_response=_intent(message_type="recommendation", month=9)
        )
        get_travel_recommendation(
            "someday between september and october",
            session_key="session-2",
            ai_provider=second_provider,
            climate_provider=self.climate,
        )

        sent_messages = second_provider.generate_structured_reply_calls[0]
        contents = [m.content for m in sent_messages]
        self.assertIn("what do you suggest for a destination?", contents)
        self.assertIn("What month are you planning to travel?", contents)

    def test_different_sessions_do_not_share_history(self):
        first_provider = StubAIProvider(structured_response=_intent(message_type="off_topic"))
        get_travel_recommendation(
            "message from session A",
            session_key="session-a",
            ai_provider=first_provider,
            climate_provider=self.climate,
        )

        second_provider = StubAIProvider(structured_response=_intent(message_type="off_topic"))
        get_travel_recommendation(
            "message from session B",
            session_key="session-b",
            ai_provider=second_provider,
            climate_provider=self.climate,
        )

        sent_messages = second_provider.generate_structured_reply_calls[0]
        self.assertEqual(len(sent_messages), 2)  # no session-a history leaked in

    def test_authenticated_user_history_persists_regardless_of_session(self):
        user = User.objects.create_user(email="traveler@example.com", password="testpass123")
        first_provider = StubAIProvider(structured_response=_intent(message_type="off_topic"))
        get_travel_recommendation(
            "first message",
            user=user,
            session_key="session-x",
            ai_provider=first_provider,
            climate_provider=self.climate,
        )

        second_provider = StubAIProvider(structured_response=_intent(message_type="off_topic"))
        get_travel_recommendation(
            "second message",
            user=user,
            session_key="session-y",  # different session, same user
            ai_provider=second_provider,
            climate_provider=self.climate,
        )

        contents = [m.content for m in second_provider.generate_structured_reply_calls[0]]
        self.assertIn("first message", contents)

    def test_streamed_reply_is_saved_to_history_once_fully_consumed(self):
        ai_provider = StubAIProvider(
            structured_response=_intent(
                message_type="recommendation", month=10, min_temp_c=25.0
            ),
            reply_text="Try the warm-cheap destination!",
        )

        result = stream_travel_recommendation(
            "somewhere warm in October",
            session_key="session-stream",
            ai_provider=ai_provider,
            climate_provider=self.climate,
        )
        full_reply = "".join(result.reply_chunks)

        key = memory.conversation_key(user=None, session_key="session-stream")
        history = memory.get_history(key)
        self.assertEqual(history[-1], {"role": "assistant", "content": full_reply})
