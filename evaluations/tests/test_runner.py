from unittest.mock import patch

from django.test import TestCase

from ai.provider.base import AIProviderError
from evaluations.runner import run_scenarios, select_scenarios
from evaluations.scenarios import Scenario
from evaluations.weather_fixtures import FixtureWeatherProvider, MissingWeatherFixtureError
from integrations.climate.base import MonthlyClimateSummary
from travel.models import Destination


class _MissingFixtureClimate:
    """Mirrors what evaluations.weather_fixtures.FixtureWeatherProvider
    does for a coordinate/month with no captured entry - used to test
    the runner's own MissingWeatherFixtureError handling without
    depending on the real fixture file's actual coverage."""

    def get_monthly_climate(self, *, latitude, longitude, month, year=None):
        raise MissingWeatherFixtureError(latitude, longitude, month)


class _StubClimate:
    def get_monthly_climate(self, *, latitude, longitude, month, year=None):
        return MonthlyClimateSummary(2025, month, 25.0, 18.0, 5.0)


def _intent(**overrides):
    base = {
        "message_type": "recommendation",
        "month": 7,
        "min_temp_c": None,
        "max_temp_c": None,
        "max_cost_of_living": None,
        "trip_type": "beach",
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
    base.update(overrides)
    return base


class StubAIProvider:
    """Schema-aware double for the AIProvider ABC - returns a canned
    intent for the combined extraction call, a canned climate/budget
    signal for the isolated call, and streams a fixed reply."""

    def __init__(self, *, intent, climate_budget=None, reply_text="Here is a great option."):
        self.intent = intent
        self.climate_budget = climate_budget or {
            "min_temp_c": intent.get("min_temp_c"),
            "max_temp_c": intent.get("max_temp_c"),
            "max_cost_of_living": intent.get("max_cost_of_living"),
        }
        self.reply_text = reply_text
        self.model = "stub-model"

    def generate_structured_reply(
        self, messages, *, json_schema, max_tokens=None, temperature=None
    ):
        if json_schema["name"] == "travel_message":
            return self.intent
        if json_schema["name"] == "climate_budget_signal":
            return self.climate_budget
        raise AssertionError(f"unexpected schema {json_schema['name']}")

    def generate_reply(self, messages, *, max_tokens=None):
        from ai.provider.base import AIResponse

        return AIResponse(
            content=self.reply_text, model=self.model, prompt_tokens=0, completion_tokens=0
        )

    def stream_reply(self, messages, *, max_tokens=None, temperature=None):
        for word in self.reply_text.split(" "):
            yield word + " "


class _StreamFailingAIProvider:
    """Intent extraction succeeds normally (so the failure isn't masked
    by ai.orchestration's own internal extract_intent fallback, which
    degrades to FALLBACK_REPLY without ever raising past that point) -
    only the final explanation stream fails, which propagates through
    "".join(result.reply_chunks) and is exactly what evaluations.runner's
    own except AIProviderError block exists to catch."""

    def __init__(self, intent):
        self.intent = intent

    def generate_structured_reply(
        self, messages, *, json_schema, max_tokens=None, temperature=None
    ):
        if json_schema["name"] == "travel_message":
            return self.intent
        return {
            "min_temp_c": self.intent.get("min_temp_c"),
            "max_temp_c": self.intent.get("max_temp_c"),
            "max_cost_of_living": self.intent.get("max_cost_of_living"),
        }

    def generate_reply(self, messages, *, max_tokens=None):
        raise AIProviderError("boom")

    def stream_reply(self, messages, *, max_tokens=None, temperature=None):
        raise AIProviderError("boom")
        yield ""  # pragma: no cover - makes this a generator function


def _destination(slug, **kwargs):
    defaults = dict(
        name=slug,
        country="Testland",
        latitude=10.0,
        longitude=10.0,
        trip_type="beach",
        cost_of_living=2,
        best_season="x",
        worst_season="x",
        short_description="x",
        points_of_interest=[],
    )
    defaults.update(kwargs)
    return Destination.objects.create(slug=slug, **defaults)


class SelectScenariosTests(TestCase):
    def test_filters_by_split(self):
        scenarios = [
            Scenario(id="D1", split="dev", category="straightforward", message="x"),
            Scenario(id="H1", split="holdout", category="straightforward", message="x"),
        ]
        selected = select_scenarios(scenarios, split="dev", sample=None)
        self.assertEqual([s.id for s in selected], ["D1"])

    def test_sample_reduces_count_deterministically(self):
        scenarios = [
            Scenario(id=f"D{i}", split="dev", category="straightforward", message="x")
            for i in range(10)
        ]
        first = select_scenarios(scenarios, split="dev", sample=3, seed=42)
        second = select_scenarios(scenarios, split="dev", sample=3, seed=42)
        self.assertEqual(len(first), 3)
        self.assertEqual([s.id for s in first], [s.id for s in second])

    def test_sample_larger_than_pool_returns_everything(self):
        scenarios = [Scenario(id="D1", split="dev", category="straightforward", message="x")]
        selected = select_scenarios(scenarios, split="dev", sample=50)
        self.assertEqual(len(selected), 1)


class DeterministicRunTests(TestCase):
    def test_deterministic_mode_makes_no_ai_calls_and_returns_results(self):
        _destination("cheap", cost_of_living=1)
        _destination("expensive", cost_of_living=5)
        scenario = Scenario(
            id="T-1",
            split="dev",
            category="straightforward",
            message="x",
            deterministic_request={"month": 6, "max_cost_of_living": 2},
            acceptable_slugs=("cheap",),
        )

        results, cost = run_scenarios(
            [scenario], deterministic_only=True, climate_provider=_StubClimate()
        )

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].passed)
        self.assertEqual(cost.pipeline_scenarios, 0)
        self.assertEqual(cost.estimated_usd, 0.0)

    def test_deterministic_mode_with_no_deterministic_request_still_runs(self):
        scenario = Scenario(id="T-1", split="dev", category="ambiguous", message="x")
        results, _ = run_scenarios(
            [scenario], deterministic_only=True, climate_provider=_StubClimate()
        )
        self.assertEqual(results[0].scored, [])

    @patch("recommendations.scoring.CLIMATE_LOOKUP_TIME_BUDGET_SECONDS", 0.01)
    def test_determinism_recheck_is_skipped_when_time_budget_was_hit(self):
        # A real finding from the first baseline smoke test: re-running
        # scoring with a second, freshly-timed budget after the first
        # pass already hit CLIMATE_LOOKUP_TIME_BUDGET_SECONDS can
        # legitimately reach a different number of (unordered, only
        # partially cached) candidates - that's the time budget working
        # as designed, not non-deterministic ranking. The recheck must
        # not run at all in that case, rather than flag a false positive.
        import time as time_module

        _destination("slow-a", cost_of_living=1)
        _destination("slow-b", cost_of_living=1)
        scenario = Scenario(
            id="T-1",
            split="dev",
            category="straightforward",
            message="x",
            deterministic_request={"month": 6},
        )

        class _SlowClimate:
            def get_monthly_climate(self, *, latitude, longitude, month, year=None):
                time_module.sleep(0.05)
                return MonthlyClimateSummary(2025, month, 25.0, 18.0, 5.0)

        results, _ = run_scenarios(
            [scenario], deterministic_only=True, climate_provider=_SlowClimate()
        )

        self.assertTrue(results[0].trace.time_budget_exceeded)
        check_names = [inv.name for inv in results[0].invariants]
        self.assertNotIn("ranking_deterministic_for_identical_input", check_names)

    def test_determinism_recheck_works_for_a_profile_scenario_with_zero_candidates(self):
        # Real bug found while running the whole corpus deterministic-
        # only: a scenario with profile_overrides (so it gets a real,
        # synthetic_traveler-created User) whose deterministic_request
        # happens to match zero DB-level candidates never calls the
        # climate provider at all - so it reaches the determinism
        # recheck below without ever hitting run_scenarios' own
        # MissingWeatherFixtureError handling. The recheck used to run
        # AFTER `with synthetic_traveler(...) as user:` had already
        # exited, by which point synthetic_traveler's own `finally`
        # block had called user.delete() - and Django resets a deleted
        # instance's .pk to None, so the second scoring pass's
        # Trip/TravelHistoryEntry queries (filtered by that same user
        # object) crashed with "Model instances passed to related
        # filters must be saved." No real destination is tagged
        # trip_type="nonexistent-type" here, so the request always
        # resolves to zero candidates regardless of catalog contents.
        scenario = Scenario(
            id="T-1",
            split="dev",
            category="straightforward",
            message="x",
            deterministic_request={"month": 6, "trip_type": "nonexistent-type"},
            profile_overrides={"preferred_trip_types": ["beach"]},
        )

        results, _ = run_scenarios(
            [scenario], deterministic_only=True, climate_provider=_StubClimate()
        )

        result = results[0]
        self.assertFalse(result.is_infrastructure_failure)
        self.assertEqual(result.scored, [])
        check_names = [inv.name for inv in result.invariants]
        self.assertIn("ranking_deterministic_for_identical_input", check_names)

    def test_missing_weather_fixture_is_tagged_as_infrastructure_failure_not_quality_failure(self):
        # Cycle 1.5's core distinction: "is Wanderes' recommendation
        # logic correct" and "is the weather fixture complete" are
        # different questions - a missing fixture must never be reported
        # as a SCORING/HARD_CONSTRAINT product-quality failure.
        _destination("somewhere", cost_of_living=1)
        scenario = Scenario(
            id="T-1",
            split="dev",
            category="straightforward",
            message="x",
            deterministic_request={"month": 6},
        )

        results, _ = run_scenarios(
            [scenario], deterministic_only=True, climate_provider=_MissingFixtureClimate()
        )

        result = results[0]
        self.assertTrue(result.is_infrastructure_failure)
        self.assertFalse(result.evaluable)
        self.assertFalse(result.passed)
        self.assertEqual(result.failed_check_names(), ["dependency_failure"])
        self.assertIsNotNone(result.infrastructure_failure_reason)

    def test_empty_fixture_provider_never_falls_through_to_the_live_provider(self):
        # The sharper version of test_weather_fixtures's own truthiness
        # regression test: proves the fix holds through the real
        # production call site, not just in isolation. recommendations.
        # scoring.generate_recommendations does
        # `climate_provider = climate_provider or get_climate_provider()`
        # - before FixtureWeatherProvider defined __bool__, passing one
        # with zero entries (the real state of a fresh checkout before
        # refresh_weather_fixtures ever runs) was falsy, silently
        # routing every deterministic evaluation scenario to the real,
        # live Open-Meteo provider instead of the fixture.
        _destination("somewhere", cost_of_living=1)
        scenario = Scenario(
            id="T-1",
            split="dev",
            category="straightforward",
            message="x",
            deterministic_request={"month": 6},
        )
        import tempfile
        from pathlib import Path

        empty_fixture = FixtureWeatherProvider(Path(tempfile.mkdtemp()) / "empty.json")
        self.assertEqual(len(empty_fixture), 0)

        with patch("recommendations.scoring.get_climate_provider") as mock_get_live:
            mock_get_live.side_effect = AssertionError(
                "must never construct the live climate provider in deterministic mode"
            )
            results, _ = run_scenarios(
                [scenario], deterministic_only=True, climate_provider=empty_fixture
            )

        mock_get_live.assert_not_called()
        self.assertTrue(results[0].is_infrastructure_failure)

    def test_run_scenarios_defaults_to_the_fixture_provider_not_live_network(self):
        # evaluations.runner.run_scenarios()'s climate_provider defaults
        # to FixtureWeatherProvider() for BOTH deterministic-only and
        # full-pipeline modes when the caller passes none - this is what
        # keeps "is scoring correct" and "is Open-Meteo up right now"
        # from ever being answered by the same live call again.
        with patch("evaluations.runner.FixtureWeatherProvider") as mock_provider_cls:
            mock_provider_cls.return_value = _StubClimate()
            scenario = Scenario(id="T-1", split="dev", category="ambiguous", message="x")
            run_scenarios([scenario], deterministic_only=True)
        mock_provider_cls.assert_called_once_with()

    def test_deterministic_rerun_with_same_input_produces_identical_scored_slugs(self):
        # §7: the deterministic portion must be reproducible run over
        # run against the exact same commit/corpus/fixtures.
        _destination("a", cost_of_living=1, trip_type="beach")
        _destination("b", cost_of_living=2, trip_type="beach")
        scenario = Scenario(
            id="T-1",
            split="dev",
            category="straightforward",
            message="x",
            deterministic_request={"month": 6, "trip_type": "beach"},
        )

        first, _ = run_scenarios(
            [scenario], deterministic_only=True, climate_provider=_StubClimate()
        )
        second, _ = run_scenarios(
            [scenario], deterministic_only=True, climate_provider=_StubClimate()
        )

        self.assertEqual(first[0].scored_slugs, second[0].scored_slugs)


class FullPipelineInfrastructureFailureTests(TestCase):
    def test_missing_weather_fixture_in_full_pipeline_is_infrastructure_failure(self):
        _destination("beach-1", trip_type="beach", cost_of_living=1)
        scenario = Scenario(id="T-1", split="dev", category="straightforward", message="x")
        provider = StubAIProvider(intent=_intent(trip_type="beach"))

        results, _ = run_scenarios(
            [scenario],
            deterministic_only=False,
            ai_provider=provider,
            climate_provider=_MissingFixtureClimate(),
        )

        result = results[0]
        self.assertTrue(result.is_infrastructure_failure)
        self.assertFalse(result.passed)
        self.assertIsNone(result.error)


class FullPipelineRunTests(TestCase):
    def test_successful_scenario_passes(self):
        _destination("beach-1", trip_type="beach", cost_of_living=1)
        scenario = Scenario(
            id="T-1",
            split="dev",
            category="straightforward",
            message="quero uma praia barata em julho",
            expected_intent={"trip_type": "beach"},
            deterministic_request={"month": 7, "trip_type": "beach"},
        )
        provider = StubAIProvider(
            intent=_intent(trip_type="beach"), reply_text="beach-1 is a great warm choice."
        )

        results, cost = run_scenarios(
            [scenario],
            deterministic_only=False,
            ai_provider=provider,
            climate_provider=_StubClimate(),
        )

        result = results[0]
        self.assertTrue(result.flow_matched)
        self.assertTrue(result.intent_eval.all_match)
        self.assertTrue(result.passed)
        self.assertEqual(cost.pipeline_scenarios, 1)
        self.assertGreater(cost.estimated_usd, 0.0)

    def test_flow_mismatch_is_detected(self):
        scenario = Scenario(
            id="T-1",
            split="dev",
            category="robustness",
            message="quais os requisitos de visto",
            expected_flow="visa",
        )
        # Stub returns an intent that is NOT a visa question at all.
        provider = StubAIProvider(intent=_intent(is_visa_or_entry_question=False))

        results, _ = run_scenarios(
            [scenario],
            deterministic_only=False,
            ai_provider=provider,
            climate_provider=_StubClimate(),
        )

        self.assertFalse(results[0].flow_matched)
        self.assertFalse(results[0].passed)
        self.assertIn("flow_mismatch", results[0].failed_check_names())

    def test_mid_stream_failure_degrades_to_fallback_reply_without_crashing(self):
        # ai.orchestration._stream_ai_reply is the sole caller of
        # AIProvider.stream_reply and already catches AIProviderError
        # internally, yielding FALLBACK_REPLY instead of propagating - so
        # a real mid-stream failure never actually reaches the runner's
        # own except block (see the next test for that).
        from ai.orchestration import FALLBACK_REPLY

        scenario = Scenario(id="T-1", split="dev", category="straightforward", message="x")
        provider = _StreamFailingAIProvider(_intent())

        results, _ = run_scenarios(
            [scenario],
            deterministic_only=False,
            ai_provider=provider,
            climate_provider=_StubClimate(),
        )

        self.assertIsNone(results[0].error)
        self.assertIn(FALLBACK_REPLY, results[0].reply)

    def test_runners_own_error_boundary_catches_whatever_orchestration_lets_through(self):
        # Defensive belt-and-suspenders: ai.orchestration.stream_travel_recommendation
        # never actually raises AIProviderError today (every internal AI
        # call already catches and degrades it), but the runner still
        # guards against it directly in case that ever changes, or a
        # different orchestration entry point doesn't. Exercised here by
        # mocking the entry point itself, since there's no way to
        # provoke this through the real, already-defensive pipeline.
        from ai.provider.base import AIProviderError as RealAIProviderError

        scenario = Scenario(id="T-1", split="dev", category="straightforward", message="x")
        with patch("evaluations.runner.stream_travel_recommendation") as mock_stream:
            mock_stream.side_effect = RealAIProviderError("boom")
            results, _ = run_scenarios(
                [scenario],
                deterministic_only=False,
                ai_provider=StubAIProvider(intent=_intent()),
                climate_provider=_StubClimate(),
            )

        self.assertEqual(results[0].error, "boom")
        self.assertFalse(results[0].passed)

    def test_intent_extraction_failure_degrades_gracefully_without_an_exception(self):
        # ai.orchestration.stream_travel_recommendation catches this
        # internally and returns FALLBACK_REPLY rather than raising -
        # the runner should see a completed (not errored) result, just
        # one that fails its own checks (no scored destinations at all
        # for a scenario that expected some).
        class _ExtractionFailingProvider:
            def generate_structured_reply(
                self, messages, *, json_schema, max_tokens=None, temperature=None
            ):
                raise AIProviderError("boom")

            def generate_reply(self, messages, *, max_tokens=None):
                raise AIProviderError("boom")

            def stream_reply(self, messages, *, max_tokens=None, temperature=None):
                raise AIProviderError("boom")
                yield ""  # pragma: no cover

        scenario = Scenario(id="T-1", split="dev", category="straightforward", message="x")
        results, _ = run_scenarios(
            [scenario],
            deterministic_only=False,
            ai_provider=_ExtractionFailingProvider(),
            climate_provider=_StubClimate(),
        )
        self.assertIsNone(results[0].error)
        self.assertEqual(results[0].scored, [])

    def test_excluded_destination_violation_fails_the_scenario(self):
        _destination("banned", trip_type="beach", cost_of_living=1)
        scenario = Scenario(
            id="T-1",
            split="dev",
            category="straightforward",
            message="quero praia sem banned",
            deterministic_request={"month": 6, "trip_type": "beach", "excluded_slugs": ["banned"]},
            must_not_include_slugs=("banned",),
        )
        # Stub's extracted intent doesn't actually carry the exclusion -
        # simulates a real extraction failure reaching scoring.
        provider = StubAIProvider(intent=_intent(trip_type="beach", excluded_place_names=[]))

        results, _ = run_scenarios(
            [scenario],
            deterministic_only=False,
            ai_provider=provider,
            climate_provider=_StubClimate(),
        )

        self.assertFalse(results[0].passed)

    def test_scenario_result_to_json_is_serializable(self):
        import json

        _destination("beach-1", trip_type="beach", cost_of_living=1)
        scenario = Scenario(
            id="T-1",
            split="dev",
            category="straightforward",
            message="x",
            deterministic_request={"month": 6},
        )
        results, _ = run_scenarios(
            [scenario], deterministic_only=True, climate_provider=_StubClimate()
        )
        json.dumps(results[0].to_json())  # must not raise
