from unittest.mock import Mock, patch

from django.test import TestCase

from integrations.climate.base import ClimateProviderError, MonthlyClimateSummary
from integrations.tasks import warm_climate_cache
from travel.models import Destination


def _make_destination(slug, *, lat=10.0, lon=10.0):
    return Destination.objects.create(
        slug=slug,
        name=slug,
        country="Testland",
        latitude=lat,
        longitude=lon,
        trip_type="beach",
        cost_of_living=1,
        best_season="Jan-Dec",
        worst_season="None",
        short_description="A test destination.",
        points_of_interest=[],
    )


@patch("integrations.tasks.time.sleep")  # the real inter-call delay shouldn't slow down a unit test
class WarmClimateCacheTests(TestCase):
    @patch("integrations.tasks.get_climate_provider")
    def test_calls_climate_provider_for_every_destination_and_month(
        self, mock_get_provider, mock_sleep
    ):
        _make_destination("dest-a")
        _make_destination("dest-b")
        stub_provider = Mock()
        stub_provider.get_monthly_climate.return_value = MonthlyClimateSummary(
            2025, 1, 20.0, 10.0, 5.0
        )
        mock_get_provider.return_value = stub_provider

        result = warm_climate_cache()

        self.assertEqual(stub_provider.get_monthly_climate.call_count, 2 * 12)
        self.assertEqual(result, {"warmed": 24, "failed": 0})
        # A real delay must actually happen between calls (2026-09-02 fix -
        # an undelayed burst is what triggered the original hang) - just
        # not a real one slowing down this test.
        self.assertEqual(mock_sleep.call_count, 24)

    @patch("integrations.tasks.get_climate_provider")
    def test_a_failed_lookup_is_counted_and_does_not_stop_the_rest(
        self, mock_get_provider, mock_sleep
    ):
        _make_destination("dest-a")
        stub_provider = Mock()
        stub_provider.get_monthly_climate.side_effect = ClimateProviderError("boom")
        mock_get_provider.return_value = stub_provider

        result = warm_climate_cache()

        self.assertEqual(stub_provider.get_monthly_climate.call_count, 12)
        self.assertEqual(result, {"warmed": 0, "failed": 12})

    @patch("integrations.tasks.get_climate_provider")
    def test_no_destinations_is_a_no_op(self, mock_get_provider, mock_sleep):
        stub_provider = Mock()
        mock_get_provider.return_value = stub_provider

        result = warm_climate_cache()

        stub_provider.get_monthly_climate.assert_not_called()
        mock_sleep.assert_not_called()
        self.assertEqual(result, {"warmed": 0, "failed": 0})
