from decimal import Decimal

from django.test import TestCase

from ai import memory
from ai.orchestration import (
    FALLBACK_REPLY,
    MAX_RECOMMENDATIONS,
    NEEDS_LOGIN_REPLY,
    get_travel_recommendation,
    stream_travel_recommendation,
)
from ai.provider.base import AIProviderError, AIResponse
from analytics.models import Event
from integrations.climate.base import ClimateProviderError, MonthlyClimateSummary
from travel.models import CountryEntryRequirement, Destination
from travel.services import ENTRY_REQUIREMENT_DISCLAIMER
from trips.models import Feedback, TravelHistoryEntry, Trip
from users.currency import convert_to_usd
from users.models import TravelerProfile, User


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
        self.generate_reply_calls = []

    def generate_structured_reply(
        self, messages, *, json_schema, max_tokens=None, temperature=None
    ):
        self.generate_structured_reply_calls.append(messages)
        return self.structured_response

    def generate_reply(self, messages, *, max_tokens=None):
        # Used by _localize_reply (2026-08-31) to phrase a fixed feedback/
        # future-intent confirmation in the traveler's language. Echoing
        # the original English fact back verbatim (stripping the wrapping
        # localization instruction) keeps every existing assertion against
        # those exact fact strings valid - actual localization quality is
        # a live-only concern this stub isn't meant to exercise.
        self.generate_reply_calls.append(messages)
        last_content = messages[-1].content
        marker = "this applies just as much to English as to any other language: "
        idx = last_content.find(marker)
        content = last_content[idx + len(marker) :] if idx != -1 else last_content
        return AIResponse(content=content, model="stub", prompt_tokens=0, completion_tokens=0)

    def stream_reply(self, messages, *, max_tokens=None):
        self.stream_reply_calls.append(messages)
        for word in self.reply_text.split(" "):
            yield word + " "


class FailingAIProvider:
    def generate_structured_reply(
        self, messages, *, json_schema, max_tokens=None, temperature=None
    ):
        raise AIProviderError("boom")

    def generate_reply(self, messages, *, max_tokens=None):
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
    month=None,
    min_temp_c=None,
    max_temp_c=None,
    max_cost_of_living=None,
    trip_type=None,
    excluded_place_names=None,
    feedback_destination_name=None,
    feedback_rating=None,
    feedback_tags=None,
    feedback_comment=None,
    future_destination_name=None,
    is_recall_request=False,
):
    return {
        "message_type": message_type,
        "month": month,
        "min_temp_c": min_temp_c,
        "max_temp_c": max_temp_c,
        "max_cost_of_living": max_cost_of_living,
        "trip_type": trip_type,
        "excluded_place_names": excluded_place_names or [],
        "feedback_destination_name": feedback_destination_name,
        "feedback_rating": feedback_rating,
        "feedback_tags": feedback_tags or [],
        "feedback_comment": feedback_comment,
        "future_destination_name": future_destination_name,
        "is_recall_request": is_recall_request,
    }


class GetTravelRecommendationTests(TestCase):
    """Tests the non-streaming convenience wrapper (joined chunks)."""

    def setUp(self):
        self.destination = _make_destination("warm-cheap", lat=10.0, lon=10.0)
        self.climate = StubClimateProvider(
            {(10.0, 10.0): MonthlyClimateSummary(2025, 10, 28.0, 20.0, 5.0)}
        )

    def test_off_topic_message_gets_a_real_ai_reply(self):
        # 2026-08-30, direct user feedback: returning the exact same fixed
        # sentence for every off-topic message (even "are you an AI?")
        # felt scripted, not like a real assistant. Off-topic now makes a
        # real AI call instead of returning a canned string.
        ai_provider = StubAIProvider(
            structured_response=_intent(message_type="off_topic"),
            reply_text="Paris is the capital of France! Now, where are you thinking of traveling?",
        )

        result = get_travel_recommendation(
            "what's the capital of France?", ai_provider=ai_provider, climate_provider=self.climate
        )

        self.assertEqual(
            result.reply,
            "Paris is the capital of France! Now, where are you thinking of traveling? ",
        )
        self.assertEqual(result.recommendations, [])
        self.assertEqual(len(ai_provider.stream_reply_calls), 1)

    def test_missing_month_defaults_to_current_month_and_proceeds(self):
        # No clarification gate (removed 2026-08-30, per direct user
        # feedback): a real user will rarely state every dimension in one
        # message, and should never be blocked from a real answer for it -
        # month defaults to the current one instead of being asked about.
        ai_provider = StubAIProvider(
            structured_response=_intent(min_temp_c=20.0),
            reply_text="Try the warm destination!",
        )

        result = get_travel_recommendation(
            "somewhere warm", ai_provider=ai_provider, climate_provider=self.climate
        )

        self.assertEqual(len(result.recommendations), 1)
        explanation_messages = ai_provider.stream_reply_calls[0]
        self.assertTrue(
            any("assumed" in m.content for m in explanation_messages if m.role == "user")
        )

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

    def test_max_temp_c_is_wired_through_to_recommendation_request(self):
        # 2026-09-02 review: max_temp_c existed as a hard constraint in
        # recommendations.scoring.RecommendationRequest since Phase 8, but
        # nothing in the AI orchestration layer ever extracted or passed
        # it - "somewhere not too hot" could never actually be honored.
        # warm-cheap's real avg_high_c for month 10 is 28.0 (see setUp) -
        # a max_temp_c of 25.0 should filter it out entirely.
        ai_provider = StubAIProvider(
            structured_response=_intent(month=10, max_temp_c=25.0),
            reply_text="Here are some cooler options.",
        )

        result = get_travel_recommendation(
            "somewhere not too hot in October",
            ai_provider=ai_provider,
            climate_provider=self.climate,
        )

        self.assertEqual(result.recommendations, [])

    def test_max_temp_c_alone_is_enough_signal_to_search(self):
        # Mirrors the existing min_temp_c-alone-is-enough-signal behavior -
        # a traveler rarely states an explicit temperature bound without
        # real intent, so max_temp_c alone should also skip the "gather
        # more first" open-ended path and search immediately. 30.0 is
        # above warm-cheap's real 28.0 avg_high_c, so it should match.
        ai_provider = StubAIProvider(
            structured_response=_intent(month=10, max_temp_c=30.0),
            reply_text="Try this one!",
        )

        result = get_travel_recommendation(
            "somewhere not too hot in October",
            ai_provider=ai_provider,
            climate_provider=self.climate,
        )

        self.assertEqual(len(result.recommendations), 1)
        self.assertEqual(result.recommendations[0].destination.slug, "warm-cheap")

    def test_completely_open_ended_message_lets_ai_decide_instead_of_searching(self):
        # Reported live: "oi, pode me ajudar com uma viagem?" (hi, can you
        # help me with a trip?) with genuinely nothing else - no month,
        # climate, budget, trip type - jumped straight to specific
        # destination suggestions, which felt presumptuous. When there is
        # truly no signal at all, the app should hand the "ask vs suggest"
        # judgment to the AI rather than running an unfiltered search.
        ai_provider = StubAIProvider(
            structured_response=_intent(),  # everything null - a bare opener
            reply_text="What kind of trip are you dreaming about?",
        )

        result = get_travel_recommendation(
            "hi, can you help me with a trip?",
            ai_provider=ai_provider,
            climate_provider=self.climate,
        )

        self.assertEqual(result.reply, "What kind of trip are you dreaming about? ")
        self.assertEqual(result.recommendations, [])
        self.assertEqual(len(ai_provider.stream_reply_calls), 1)

    def test_no_matches_asks_ai_to_help_instead_of_a_dead_end_reply(self):
        # Per the Phase 11 recommendation philosophy and direct user
        # feedback: a hard-constraint dead end should not be a canned
        # message - the AI should always try to help from its own
        # knowledge rather than asking yet another question.
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

    def test_invalid_month_from_ai_defaults_to_current_month(self):
        ai_provider = StubAIProvider(
            structured_response=_intent(month=42, min_temp_c=20.0),
            reply_text="Try somewhere nice!",
        )

        result = get_travel_recommendation(
            "somewhere nice and warm sometime",
            ai_provider=ai_provider,
            climate_provider=self.climate,
        )

        self.assertEqual(len(result.recommendations), 1)

    def test_ai_provider_error_returns_fallback_reply(self):
        result = get_travel_recommendation(
            "somewhere warm in October",
            ai_provider=FailingAIProvider(),
            climate_provider=self.climate,
        )

        self.assertEqual(result.reply, FALLBACK_REPLY)
        self.assertEqual(result.recommendations, [])


class TravelerProfileContextTests(TestCase):
    """Tests that TravelerProfile's home_country/travelers_count/budget
    (2026-09-02) reach the AI's reasoning prompts as context, and that
    CountryEntryRequirement data is looked up (not invented) when a home
    country is known."""

    def setUp(self):
        self.destination = _make_destination("warm-cheap", lat=10.0, lon=10.0)
        self.climate = StubClimateProvider(
            {(10.0, 10.0): MonthlyClimateSummary(2025, 10, 28.0, 20.0, 5.0)}
        )
        self.user = User.objects.create_user(email="traveler@example.com", password="testpass123")

    def test_profile_budget_and_travelers_reach_the_explanation_prompt(self):
        TravelerProfile.objects.create(
            user=self.user,
            home_country="Brazil",
            travelers_count=3,
            budget_amount=150,
            budget_currency="BRL",
            budget_period="day",
        )
        # Bypasses the 2026-09-02 confirmation gate (its own dedicated
        # tests are in ProfileConfirmationGateTests below) - this test is
        # specifically about what the explanation prompt contains, not
        # about the gate itself.
        memory.mark_profile_confirmed(memory.conversation_key(user=self.user, session_key=None))
        ai_provider = StubAIProvider(
            structured_response=_intent(month=10, min_temp_c=20.0), reply_text="Here you go!"
        )

        get_travel_recommendation(
            "somewhere warm in October",
            user=self.user,
            ai_provider=ai_provider,
            climate_provider=self.climate,
        )

        explanation_prompt = ai_provider.stream_reply_calls[0][-1].content
        self.assertIn("traveling from Brazil", explanation_prompt)
        self.assertIn("3 people", explanation_prompt)
        # Always converted to an approximate USD figure (2026-09-02 direct
        # follow-up: "budget must be always on dolar") - never the raw
        # currency-ambiguous number handed to the AI directly. Computed
        # from the same conversion table rather than hardcoding the
        # expected figure, so this test doesn't break if the static rates
        # in users/currency.py are ever updated.
        expected_usd = convert_to_usd(Decimal("150"), "BRL")
        self.assertIn(f"${expected_usd:.0f} USD", explanation_prompt)
        self.assertIn("150.00 BRL", explanation_prompt)
        self.assertIn("per day", explanation_prompt)

    def test_anonymous_user_gets_no_traveler_context(self):
        ai_provider = StubAIProvider(
            structured_response=_intent(month=10, min_temp_c=20.0), reply_text="Here you go!"
        )

        get_travel_recommendation(
            "somewhere warm in October", ai_provider=ai_provider, climate_provider=self.climate
        )

        explanation_prompt = ai_provider.stream_reply_calls[0][-1].content
        self.assertNotIn("Traveler profile context", explanation_prompt)

    def test_budget_without_a_period_is_not_included(self):
        # The profile form itself requires all three together, but the
        # orchestration layer shouldn't trust that - a directly-created
        # row with only one of the trio set must not surface a
        # meaningless "amount with no unit/currency" note.
        TravelerProfile.objects.create(user=self.user, budget_amount=150)
        ai_provider = StubAIProvider(
            structured_response=_intent(month=10, min_temp_c=20.0), reply_text="Here you go!"
        )

        get_travel_recommendation(
            "somewhere warm in October",
            user=self.user,
            ai_provider=ai_provider,
            climate_provider=self.climate,
        )

        explanation_prompt = ai_provider.stream_reply_calls[0][-1].content
        self.assertNotIn("budget", explanation_prompt.lower())

    def test_budget_without_a_currency_is_not_included(self):
        # A pre-migration or directly-created row could have amount+period
        # but no currency - without a currency there's nothing real to
        # convert, so this must degrade to no budget note at all rather
        # than guessing a currency.
        TravelerProfile.objects.create(user=self.user, budget_amount=150, budget_period="day")
        ai_provider = StubAIProvider(
            structured_response=_intent(month=10, min_temp_c=20.0), reply_text="Here you go!"
        )

        get_travel_recommendation(
            "somewhere warm in October",
            user=self.user,
            ai_provider=ai_provider,
            climate_provider=self.climate,
        )

        explanation_prompt = ai_provider.stream_reply_calls[0][-1].content
        self.assertNotIn("budget", explanation_prompt.lower())

    def test_entry_requirements_included_when_home_country_and_data_exist(self):
        TravelerProfile.objects.create(user=self.user, home_country="Brazil")
        CountryEntryRequirement.objects.create(
            country="Testland",
            visa_required_nationalities=["Brazil"],
            visa_notes="Apply online at least 30 days in advance.",
        )
        # Bypasses the 2026-09-02 confirmation gate - see the comment on
        # test_profile_budget_and_travelers_reach_the_explanation_prompt.
        memory.mark_profile_confirmed(memory.conversation_key(user=self.user, session_key=None))
        ai_provider = StubAIProvider(
            structured_response=_intent(month=10, min_temp_c=20.0), reply_text="Here you go!"
        )

        get_travel_recommendation(
            "somewhere warm in October",
            user=self.user,
            ai_provider=ai_provider,
            climate_provider=self.climate,
        )

        explanation_prompt = ai_provider.stream_reply_calls[0][-1].content
        self.assertIn("a visa IS required", explanation_prompt)
        self.assertIn(ENTRY_REQUIREMENT_DISCLAIMER, explanation_prompt)

    def test_entry_requirements_omitted_without_home_country(self):
        CountryEntryRequirement.objects.create(
            country="Testland", visa_required_nationalities=["Brazil"]
        )
        ai_provider = StubAIProvider(
            structured_response=_intent(month=10, min_temp_c=20.0), reply_text="Here you go!"
        )

        get_travel_recommendation(
            "somewhere warm in October",
            user=self.user,
            ai_provider=ai_provider,
            climate_provider=self.climate,
        )

        explanation_prompt = ai_provider.stream_reply_calls[0][-1].content
        self.assertNotIn("Entry-requirement data", explanation_prompt)


class ProfileConfirmationGateTests(TestCase):
    """Tests the 2026-09-02 gate: "IA must always confirm this information
    with the user before suggest any destination" - the first message in a
    conversation that reaches enough signal to search must confirm
    on-file TravelerProfile details first, with no destinations attached;
    every later message in that same conversation proceeds straight to
    real suggestions."""

    def setUp(self):
        self.destination = _make_destination("warm-cheap", lat=10.0, lon=10.0)
        self.climate = StubClimateProvider(
            {(10.0, 10.0): MonthlyClimateSummary(2025, 10, 28.0, 20.0, 5.0)}
        )
        self.user = User.objects.create_user(email="traveler@example.com", password="testpass123")
        TravelerProfile.objects.create(user=self.user, home_country="Brazil")

    def test_first_message_confirms_profile_instead_of_suggesting(self):
        ai_provider = StubAIProvider(
            structured_response=_intent(month=10, min_temp_c=20.0),
            reply_text="Just to confirm, still traveling from Brazil?",
        )

        result = get_travel_recommendation(
            "somewhere warm in October",
            user=self.user,
            ai_provider=ai_provider,
            climate_provider=self.climate,
        )

        self.assertEqual(result.recommendations, [])
        confirmation_prompt = ai_provider.stream_reply_calls[0][-1].content
        self.assertIn("traveling from Brazil", confirmation_prompt)
        self.assertIn("Do not suggest or list any destinations", confirmation_prompt)

    def test_second_message_in_the_conversation_proceeds_to_real_suggestions(self):
        ai_provider = StubAIProvider(
            structured_response=_intent(month=10, min_temp_c=20.0), reply_text="Here you go!"
        )

        get_travel_recommendation(  # first message: consumes the one-time gate
            "somewhere warm in October",
            user=self.user,
            ai_provider=ai_provider,
            climate_provider=self.climate,
        )
        result = get_travel_recommendation(
            "how about now?",
            user=self.user,
            ai_provider=ai_provider,
            climate_provider=self.climate,
        )

        self.assertEqual(len(result.recommendations), 1)
        self.assertEqual(result.recommendations[0].destination.slug, "warm-cheap")

    def test_no_confirmable_profile_data_skips_the_gate_entirely(self):
        user_no_profile = User.objects.create_user(
            email="noprofile@example.com", password="testpass123"
        )
        ai_provider = StubAIProvider(
            structured_response=_intent(month=10, min_temp_c=20.0), reply_text="Here you go!"
        )

        result = get_travel_recommendation(
            "somewhere warm in October",
            user=user_no_profile,
            ai_provider=ai_provider,
            climate_provider=self.climate,
        )

        self.assertEqual(len(result.recommendations), 1)


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
            def generate_structured_reply(
                self, messages, *, json_schema, max_tokens=None, temperature=None
            ):
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

    def test_off_topic_streams_a_real_ai_reply(self):
        ai_provider = StubAIProvider(
            structured_response=_intent(message_type="off_topic"),
            reply_text="Paris! Now, where are you thinking of traveling?",
        )

        result = stream_travel_recommendation(
            "what's the capital of France?", ai_provider=ai_provider, climate_provider=self.climate
        )
        chunks = list(result.reply_chunks)

        self.assertGreater(len(chunks), 1)
        self.assertEqual("".join(chunks), "Paris! Now, where are you thinking of traveling? ")
        self.assertEqual(len(ai_provider.stream_reply_calls), 1)


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

    def test_trip_type_alone_is_now_enough_signal_to_search(self):
        # 2026-09-02, direct user feedback on a real transcript: "praia"
        # (beach) with no other detail kept getting an open-ended
        # gathering question forever instead of any real answer. Reopens
        # the narrower 2026-08-31 restriction (trip_type required a
        # co-stated month too) now that the catalog is large enough (384
        # destinations) for trip_type alone to be real, differentiating
        # signal rather than a near-unfiltered dump.
        ai_provider = StubAIProvider(
            structured_response=_intent(trip_type="beach"),  # no month, no temp, no cost
            reply_text="Here are some beach options!",
        )

        result = get_travel_recommendation(
            "quero lugares de praia",
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


class RecommendationCapTests(TestCase):
    """2026-09-02, direct user request: cap recommendations at
    MAX_RECOMMENDATIONS (10) regardless of how many real destinations
    match a broad request, and tell the traveler honestly when there were
    more than that on file - the trip_type-alone fix above (same day) can
    now return dozens of real matches against the 384-destination
    catalog."""

    def _make_beach_destinations(self, count):
        climate_by_coords = {}
        for i in range(count):
            lat, lon = float(i), float(i)
            _make_destination(f"beach-{i}", lat=lat, lon=lon, trip_type="beach")
            climate_by_coords[(lat, lon)] = MonthlyClimateSummary(2025, 10, 28.0, 20.0, 5.0)
        return StubClimateProvider(climate_by_coords)

    def test_recommendations_are_capped_at_max_recommendations(self):
        climate = self._make_beach_destinations(12)
        ai_provider = StubAIProvider(
            structured_response=_intent(month=10, trip_type="beach"), reply_text="Here you go!"
        )

        result = get_travel_recommendation(
            "praia", ai_provider=ai_provider, climate_provider=climate
        )

        self.assertEqual(len(result.recommendations), MAX_RECOMMENDATIONS)

    def test_more_matches_note_appears_when_total_exceeds_the_cap(self):
        climate = self._make_beach_destinations(12)
        ai_provider = StubAIProvider(
            structured_response=_intent(month=10, trip_type="beach"), reply_text="Here you go!"
        )

        get_travel_recommendation("praia", ai_provider=ai_provider, climate_provider=climate)

        explanation_prompt = ai_provider.stream_reply_calls[0][-1].content
        self.assertIn("matched 12 destinations", explanation_prompt)
        self.assertIn(f"top {MAX_RECOMMENDATIONS}", explanation_prompt)

    def test_no_more_matches_note_when_total_is_within_the_cap(self):
        climate = self._make_beach_destinations(3)
        ai_provider = StubAIProvider(
            structured_response=_intent(month=10, trip_type="beach"), reply_text="Here you go!"
        )

        result = get_travel_recommendation(
            "praia", ai_provider=ai_provider, climate_provider=climate
        )

        self.assertEqual(len(result.recommendations), 3)
        explanation_prompt = ai_provider.stream_reply_calls[0][-1].content
        self.assertNotIn("matched", explanation_prompt)


class RecallRequestTests(TestCase):
    """2026-09-03 QA finding: "voltando, quais praias você tinha
    sugerido?" fell through to a fresh generate_recommendations() call,
    which shared only 1 of 3 destinations with what was actually
    suggested earlier - the AI re-searched instead of recalling. Fixed
    with a new is_recall_request intent field that skips search entirely
    and hands the model only its own conversation history."""

    def setUp(self):
        self.destination = _make_destination("warm-cheap", lat=10.0, lon=10.0)
        self.climate = StubClimateProvider(
            {(10.0, 10.0): MonthlyClimateSummary(2025, 10, 28.0, 20.0, 5.0)}
        )

    def test_recall_request_skips_a_new_search(self):
        ai_provider = StubAIProvider(
            structured_response=_intent(is_recall_request=True),
            reply_text="Earlier I suggested warm-cheap.",
        )

        result = get_travel_recommendation(
            "voltando, quais praias você tinha sugerido?",
            ai_provider=ai_provider,
            climate_provider=self.climate,
        )

        self.assertEqual(result.recommendations, [])
        self.assertEqual(len(ai_provider.stream_reply_calls), 1)
        recall_prompt = ai_provider.stream_reply_calls[0][-1].content
        self.assertIn("recall or repeat", recall_prompt)
        self.assertIn("Do not run a new search", recall_prompt)

    def test_recall_request_takes_priority_over_message_type(self):
        # Even a message_type the model got wrong shouldn't matter -
        # is_recall_request is checked first, before any branching on it.
        ai_provider = StubAIProvider(
            structured_response=_intent(message_type="off_topic", is_recall_request=True),
            reply_text="Sure, earlier I mentioned...",
        )

        result = get_travel_recommendation(
            "what did you say again?", ai_provider=ai_provider, climate_provider=self.climate
        )

        self.assertEqual(result.recommendations, [])
        self.assertEqual(len(ai_provider.stream_reply_calls), 1)

    def test_not_a_recall_request_still_searches_normally(self):
        ai_provider = StubAIProvider(
            structured_response=_intent(month=10, min_temp_c=20.0, is_recall_request=False),
            reply_text="Here you go!",
        )

        result = get_travel_recommendation(
            "somewhere warm in October", ai_provider=ai_provider, climate_provider=self.climate
        )

        self.assertEqual(len(result.recommendations), 1)


class PromptReinforcementTests(TestCase):
    """2026-09-03 QA-driven prompt reinforcements. These lock in that the
    strengthened instructions actually reach the model's prompt - whether
    a live model reliably follows them is a live-only concern, per this
    project's established verification pattern (see DEVELOPMENT_LOG.md)."""

    def setUp(self):
        self.destination = _make_destination("warm-cheap", lat=10.0, lon=10.0)
        self.climate = StubClimateProvider(
            {(10.0, 10.0): MonthlyClimateSummary(2025, 10, 28.0, 20.0, 5.0)}
        )

    def test_open_ended_prompt_recognizes_affirmative_go_ahead(self):
        ai_provider = StubAIProvider(structured_response=_intent(), reply_text="Sure!")

        get_travel_recommendation(
            "sim, pode buscar", ai_provider=ai_provider, climate_provider=self.climate
        )

        prompt = ai_provider.stream_reply_calls[0][-1].content
        self.assertIn("affirmative reply", prompt)
        self.assertIn("pode buscar", prompt)

    def test_open_ended_prompt_requires_real_destinations(self):
        ai_provider = StubAIProvider(structured_response=_intent(), reply_text="Sure!")

        get_travel_recommendation(
            "surpreenda-me", ai_provider=ai_provider, climate_provider=self.climate
        )

        prompt = ai_provider.stream_reply_calls[0][-1].content
        self.assertIn("must be a real, actual place", prompt)

    def test_no_matches_prompt_requires_real_destinations(self):
        ai_provider = StubAIProvider(
            structured_response=_intent(month=10, min_temp_c=1000.0), reply_text="Sure!"
        )

        get_travel_recommendation(
            "impossible request", ai_provider=ai_provider, climate_provider=self.climate
        )

        prompt = ai_provider.stream_reply_calls[0][-1].content
        self.assertIn("must be a real, actual place", prompt)

    def test_off_topic_prompt_warns_against_inventing_specifics(self):
        ai_provider = StubAIProvider(
            structured_response=_intent(message_type="off_topic"), reply_text="Sure!"
        )

        get_travel_recommendation(
            "quais companhias aéreas voam para Bali?",
            ai_provider=ai_provider,
            climate_provider=self.climate,
        )

        prompt = ai_provider.stream_reply_calls[0][-1].content
        self.assertIn("exact current price", prompt)
        self.assertIn("keep the answer general", prompt)


class UnhandledRequestLoggingTests(TestCase):
    """Per the 2026-08-29 recommendation-philosophy decision: unplanned
    requests fall to the AI's own judgment, but that fact gets logged for
    future review rather than passing silently."""

    def setUp(self):
        self.destination = _make_destination("warm-cheap", lat=10.0, lon=10.0)
        self.climate = StubClimateProvider(
            {(10.0, 10.0): MonthlyClimateSummary(2025, 10, 28.0, 20.0, 5.0)}
        )

    def test_logs_when_no_differentiating_signal_extracted(self):
        # Month alone (no trip_type/temperature/budget) isn't enough to
        # differentiate destinations by - 2026-08-31, direct user feedback:
        # this used to still run an unfiltered search and suggest whatever
        # came back. It now routes to the AI-judgment "ask vs suggest" path
        # instead, same as a fully blank opener.
        ai_provider = StubAIProvider(structured_response=_intent(month=6))

        with self.assertLogs("ai.orchestration", level="INFO") as logs:
            get_travel_recommendation(
                "a romantic getaway in June", ai_provider=ai_provider, climate_provider=self.climate
            )

        self.assertTrue(
            any(
                "Not enough signal yet to differentiate destinations" in message
                for message in logs.output
            )
        )

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

    def test_unrecognized_destination_in_future_intent_uses_ai_knowledge(self):
        # 2026-09-02, direct user feedback: "Quero ir pra monaco" previously
        # got a canned "I don't have it in my catalog, but I've noted it"
        # reply - it should now get a real AI-generated reply from general
        # knowledge instead (matching the same philosophy already used for
        # an unmatched recommendation request), and no Trip is persisted -
        # there's no valid Destination row to attach one to.
        ai_provider = StubAIProvider(
            structured_response=_intent(
                message_type="future_intent", future_destination_name="Monaco"
            ),
            reply_text="Monaco is known for its glamorous Grand Prix and casinos.",
        )

        result = get_travel_recommendation(
            "Quero ir pra monaco",
            user=self.user,
            ai_provider=ai_provider,
            climate_provider=self.climate,
        )

        self.assertIn("Monaco", result.reply)
        self.assertFalse(Trip.objects.exists())

    def test_unrecognized_destination_in_feedback_uses_ai_knowledge(self):
        # 2026-09-02 review: previously a canned "I don't have it in my
        # catalog, but thanks for sharing" reply - the same dead-end
        # pattern already fixed for future_intent, for the identical
        # underlying case (destination not in the curated catalog). Now
        # gets a real AI-generated reply instead, and still persists
        # nothing - there's no valid Destination row to attach a
        # TravelHistoryEntry/Feedback to.
        ai_provider = StubAIProvider(
            structured_response=_intent(
                message_type="feedback", feedback_destination_name="Nowhereland", feedback_rating=7
            ),
            reply_text="Nowhereland sounds like a wonderful trip!",
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
            structured_response=_intent(message_type="recommendation", min_temp_c=22.0),
            reply_text="Here's a warm suggestion for you!",
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
        self.assertIn("Here's a warm suggestion for you! ", contents)

    def test_reply_generation_call_also_receives_prior_history_not_just_extraction(self):
        # 2026-08-31, found live: a short/ambiguous follow-up like a bare
        # destination name ("Bahia") answered in English mid a Portuguese
        # conversation, because the reply-generation call (unlike the
        # intent-extraction call) was never given the conversation history
        # at all - it only ever saw the current message in isolation, with
        # nothing to judge language or continuity from. Every builder now
        # receives and forwards history; this locks that in for the
        # explanation path specifically (the one that produced the bug).
        first_provider = StubAIProvider(
            structured_response=_intent(message_type="recommendation", min_temp_c=22.0),
            reply_text="Aqui vai uma sugestão calorosa!",
        )
        get_travel_recommendation(
            "quero algo quente",
            session_key="session-history-reply",
            ai_provider=first_provider,
            climate_provider=self.climate,
        )

        second_provider = StubAIProvider(
            structured_response=_intent(message_type="recommendation", min_temp_c=22.0),
            reply_text="Outra sugestão!",
        )
        get_travel_recommendation(
            "e outras opções?",
            session_key="session-history-reply",
            ai_provider=second_provider,
            climate_provider=self.climate,
        )

        sent_messages = second_provider.stream_reply_calls[0]
        contents = [m.content for m in sent_messages]
        self.assertIn("quero algo quente", contents)
        self.assertIn("Aqui vai uma sugestão calorosa! ", contents)

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
