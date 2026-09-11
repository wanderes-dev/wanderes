from datetime import date

from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings

from integrations.flights import get_flight_provider
from integrations.flights.kayak import KayakFlightProvider


class FlightProviderFactoryTests(TestCase):
    def test_unset_provider_raises_a_friendly_error(self):
        # FLIGHT_PROVIDER defaults to blank (config/settings/base.py) -
        # using this before a provider is configured shouldn't silently
        # no-op.
        with self.assertRaises(ImproperlyConfigured):
            get_flight_provider()

    @override_settings(FLIGHT_PROVIDER="not-a-real-provider")
    def test_unknown_provider_raises(self):
        with self.assertRaises(ImproperlyConfigured):
            get_flight_provider()

    @override_settings(FLIGHT_PROVIDER="kayak")
    def test_kayak_provider_resolves(self):
        provider = get_flight_provider()

        self.assertIsInstance(provider, KayakFlightProvider)


class KayakFlightProviderSkeletonTests(TestCase):
    """KAYAK's API needs manual business approval we don't have yet
    (DECISIONS_PENDING.md §4) - this adapter is a deliberate skeleton.
    These tests just lock in that it fails loudly (NotImplementedError)
    instead of silently returning something that looks like real data."""

    def setUp(self):
        self.provider = KayakFlightProvider()

    def test_search_flights_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            self.provider.search_flights(
                origin="LIS", destination="CDG", depart_date=date(2026, 10, 1)
            )

    def test_get_flight_details_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            self.provider.get_flight_details("some-reference")

    def test_build_affiliate_link_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            self.provider.build_affiliate_link(None)
