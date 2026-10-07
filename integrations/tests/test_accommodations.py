from datetime import date

from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings

from integrations.accommodations import get_accommodation_search_link_provider
from integrations.accommodations.booking_com import (
    SEARCH_RESULTS_URL,
    BookingComSearchLinkProvider,
)


class AccommodationSearchLinkProviderFactoryTests(TestCase):
    def test_defaults_to_booking_com(self):
        provider = get_accommodation_search_link_provider()

        self.assertIsInstance(provider, BookingComSearchLinkProvider)

    @override_settings(ACCOMMODATION_SEARCH_PROVIDER="not-a-real-provider")
    def test_unknown_provider_raises(self):
        with self.assertRaises(ImproperlyConfigured):
            get_accommodation_search_link_provider()


class BookingComSearchLinkProviderTests(TestCase):
    def setUp(self):
        self.provider = BookingComSearchLinkProvider()

    def test_destination_only_search_degrades_gracefully(self):
        # This is the only shape the live chat recommendation flow ever
        # actually calls with - no dates, no party size known there.
        url = self.provider.build_search_url(destination="Tokyo", country="Japan")

        self.assertTrue(url.startswith(SEARCH_RESULTS_URL + "?"))
        self.assertIn("ss=Tokyo%2C+Japan", url)
        self.assertNotIn("checkin", url)
        self.assertNotIn("checkout", url)
        self.assertNotIn("group_adults", url)
        self.assertNotIn("group_children", url)
        self.assertNotIn("no_rooms", url)

    def test_handles_unicode_destination_names(self):
        url = self.provider.build_search_url(destination="São Paulo", country="Brazil")

        self.assertIn("ss=S%C3%A3o+Paulo%2C+Brazil", url)

    def test_includes_dates_and_party_size_when_known(self):
        url = self.provider.build_search_url(
            destination="Tokyo",
            country="Japan",
            check_in=date(2026, 10, 7),
            check_out=date(2026, 10, 21),
            adults=2,
            rooms=1,
            children=0,
        )

        self.assertIn("checkin=2026-10-07", url)
        self.assertIn("checkout=2026-10-21", url)
        self.assertIn("group_adults=2", url)
        self.assertIn("no_rooms=1", url)
        self.assertIn("group_children=0", url)

    def test_includes_one_age_param_per_child_in_order(self):
        url = self.provider.build_search_url(
            destination="Paris", country="France", children=2, child_ages=[5, 8]
        )

        self.assertIn("group_children=2", url)
        self.assertIn("age=5&age=8", url)

    def test_children_without_every_age_are_left_out_entirely(self):
        # Booking quietly reads a child with no age as age 0, so a child count
        # we can't back with ages never reaches the URL (and no age is made
        # up) - the traveler adds the child on Booking instead.
        for children, ages in ((3, [5, 8]), (1, None), (1, []), (2, [5])):
            with self.subTest(children=children, ages=ages):
                url = self.provider.build_search_url(
                    destination="Paris",
                    country="France",
                    adults=3,
                    children=children,
                    child_ages=ages,
                )

                self.assertIn("group_adults=3", url)
                self.assertNotIn("group_children", url)
                self.assertNotIn("age=", url)

    def test_a_stated_absence_of_children_is_still_sent(self):
        url = self.provider.build_search_url(
            destination="Paris", country="France", adults=2, children=0
        )

        self.assertIn("group_children=0", url)
        self.assertNotIn("age=", url)

    def test_never_includes_cj_or_affiliate_tracking_parameters(self):
        url = self.provider.build_search_url(destination="Tokyo", country="Japan")

        for banned in ["aid=", "label=", "sid=", "cjevent", "gclid"]:
            self.assertNotIn(banned, url)

    def test_never_includes_a_cj_tracking_domain(self):
        url = self.provider.build_search_url(destination="Tokyo", country="Japan")

        for tracking_domain in [
            "jdoqocy.com",
            "dpbolvw.net",
            "tkqlhce.com",
            "qksrv.net",
            "anrdoezrs.net",
        ]:
            self.assertNotIn(tracking_domain, url)
