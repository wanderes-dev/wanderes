from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings

from integrations.hotels import get_hotel_provider


class HotelProviderFactoryTests(TestCase):
    def test_unset_provider_raises_a_friendly_error(self):
        # HOTEL_PROVIDER defaults to blank (config/settings/base.py) -
        # using this before a provider is configured shouldn't silently
        # no-op.
        with self.assertRaises(ImproperlyConfigured):
            get_hotel_provider()

    @override_settings(HOTEL_PROVIDER="not-a-real-provider")
    def test_unknown_provider_raises(self):
        # No adapters are registered at all right now (Booking.com was
        # ruled out 2026-09-11 - see DECISIONS_PENDING.md §4) - any value
        # here is unknown.
        with self.assertRaises(ImproperlyConfigured):
            get_hotel_provider()
