from django.test import TestCase

from evaluations.requests import build_request
from evaluations.trace import trace_recommendations
from integrations.climate.base import ClimateProviderError, MonthlyClimateSummary
from travel.models import Destination


class _StubClimate:
    def __init__(self, *, fail_for=()):
        self.fail_for = set(fail_for)

    def get_monthly_climate(self, *, latitude, longitude, month, year=None):
        key = (round(float(latitude), 2), round(float(longitude), 2))
        if key in self.fail_for:
            raise ClimateProviderError("no data")
        return MonthlyClimateSummary(2025, month, 25.0, 18.0, 5.0)


def _destination(slug, *, lat, lon, cost_of_living=2):
    return Destination.objects.create(
        slug=slug,
        name=slug,
        country="Testland",
        latitude=lat,
        longitude=lon,
        trip_type="beach",
        cost_of_living=cost_of_living,
        best_season="x",
        worst_season="x",
        short_description="x",
        points_of_interest=[],
    )


class TraceRecommendationsTests(TestCase):
    def test_eligible_count_reflects_hard_filters(self):
        _destination("a", lat=1.0, lon=1.0, cost_of_living=1)
        _destination("b", lat=2.0, lon=2.0, cost_of_living=5)
        request = build_request({"month": 6, "max_cost_of_living": 2})

        scored, trace = trace_recommendations(request, climate_provider=_StubClimate())

        self.assertEqual(trace.eligible_after_hard_filters, 1)
        self.assertEqual(len(scored), 1)

    def test_climate_errors_are_counted(self):
        _destination("a", lat=1.0, lon=1.0)
        request = build_request({"month": 6})

        scored, trace = trace_recommendations(
            request, climate_provider=_StubClimate(fail_for={(1.0, 1.0)})
        )

        self.assertEqual(trace.climate_errors, 1)
        self.assertEqual(scored, [])

    def test_temperature_rejected_is_counted(self):
        _destination("a", lat=1.0, lon=1.0)
        request = build_request({"month": 6, "min_temp_c": 30})

        scored, trace = trace_recommendations(request, climate_provider=_StubClimate())

        self.assertEqual(trace.temperature_rejected, 1)
        self.assertEqual(scored, [])

    def test_winning_slug_matches_top_scored(self):
        _destination("a", lat=1.0, lon=1.0, cost_of_living=1)
        request = build_request({"month": 6})

        scored, trace = trace_recommendations(request, climate_provider=_StubClimate())

        self.assertEqual(trace.winning_slug, "a")

    def test_no_eligible_destinations_yields_none_winner(self):
        request = build_request({"month": 6, "country": "Nowhereland"})

        scored, trace = trace_recommendations(request, climate_provider=_StubClimate())

        self.assertIsNone(trace.winning_slug)
        self.assertEqual(trace.eligible_after_hard_filters, 0)

    def test_render_does_not_crash_and_mentions_eligible_count(self):
        _destination("a", lat=1.0, lon=1.0)
        request = build_request({"month": 6})
        _, trace = trace_recommendations(request, climate_provider=_StubClimate())
        self.assertIn("eligible", trace.render())

    def test_to_json_is_serializable(self):
        import json

        _destination("a", lat=1.0, lon=1.0)
        request = build_request({"month": 6})
        _, trace = trace_recommendations(request, climate_provider=_StubClimate())
        json.dumps(trace.to_json())  # must not raise
