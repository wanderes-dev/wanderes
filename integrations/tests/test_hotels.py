from datetime import date

from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings

from integrations.hotels import get_hotel_provider
from integrations.hotels.booking_com import BookingComHotelProvider


class HotelProviderFactoryTests(TestCase):
    def test_unset_provider_raises_a_friendly_error(self):
        # HOTEL_PROVIDER defaults to blank (config/settings/base.py) -
        # nothing should silently no-op if something tries to use this
        # before a real provider is configured.
        with self.assertRaises(ImproperlyConfigured):
            get_hotel_provider()

    @override_settings(HOTEL_PROVIDER="not-a-real-provider")
    def test_unknown_provider_raises(self):
        with self.assertRaises(ImproperlyConfigured):
            get_hotel_provider()

    @override_settings(HOTEL_PROVIDER="booking_com")
    def test_booking_com_provider_resolves(self):
        provider = get_hotel_provider()

        self.assertIsInstance(provider, BookingComHotelProvider)


class BookingComHotelProviderSkeletonTests(TestCase):
    """Booking.com's Affiliate Partner Program is application-reviewed and
    Wanderes doesn't have access yet (DECISIONS_PENDING.md §4) - this
    adapter is a deliberate skeleton, not a working implementation. These
    tests lock in that it fails loudly and clearly (NotImplementedError)
    rather than silently returning something that looks like real data."""

    def setUp(self):
        self.provider = BookingComHotelProvider()

    def test_search_hotels_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            self.provider.search_hotels(
                destination="Lisbon",
                check_in=date(2026, 10, 1),
                check_out=date(2026, 10, 5),
            )

    def test_get_hotel_details_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            self.provider.get_hotel_details("some-reference")

    def test_build_affiliate_link_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            self.provider.build_affiliate_link(None)
