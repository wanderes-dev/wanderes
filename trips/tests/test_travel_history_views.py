from django.test import TestCase
from django.urls import reverse

from travel.models import Destination
from trips.models import TravelHistoryEntry
from users.models import User


class TravelHistoryViewsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="traveler@example.com", password="testpass123")
        self.other_user = User.objects.create_user(
            email="other@example.com", password="testpass123"
        )
        self.destination = Destination.objects.create(
            slug="lisbon-pt",
            name="Lisbon",
            country="Portugal",
            latitude="38.72000",
            longitude="-9.14000",
            trip_type="city",
            cost_of_living=3,
            best_season="Mar-Oct",
            worst_season="Dec-Feb",
            short_description="A hilly coastal capital.",
            points_of_interest=[],
        )

    def test_add_creates_entry_for_current_user(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("trips:history-add"),
            {"destination": self.destination.pk, "visited_year": 2019},
        )

        self.assertRedirects(response, reverse("trips:trip-list"))
        entry = TravelHistoryEntry.objects.get(user=self.user)
        self.assertEqual(entry.destination, self.destination)
        self.assertEqual(entry.visited_year, 2019)

    def test_trip_list_shows_history_entries_for_current_user_only(self):
        # 2026-09-05, direct request: travel history is no longer its own
        # top-level page (trips:history-list removed) - it's a second
        # section on trips:trip-list instead.
        TravelHistoryEntry.objects.create(user=self.other_user, destination=self.destination)
        entry = TravelHistoryEntry.objects.create(
            user=self.user, destination=self.destination, visited_year=2019
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("trips:trip-list"))

        self.assertNotContains(response, "other@example.com")
        self.assertEqual(list(response.context["history_entries"]), [entry])

    def test_cannot_edit_another_users_entry(self):
        entry = TravelHistoryEntry.objects.create(
            user=self.other_user, destination=self.destination, visited_year=2020
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("trips:history-edit", args=[entry.pk]))

        self.assertEqual(response.status_code, 404)

    def test_edit_updates_own_entry(self):
        entry = TravelHistoryEntry.objects.create(
            user=self.user, destination=self.destination, visited_year=2018
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("trips:history-edit", args=[entry.pk]),
            {"destination": self.destination.pk, "visited_year": 2021},
        )

        self.assertRedirects(response, reverse("trips:trip-list"))
        entry.refresh_from_db()
        self.assertEqual(entry.visited_year, 2021)

    def test_delete_removes_own_entry(self):
        entry = TravelHistoryEntry.objects.create(user=self.user, destination=self.destination)
        self.client.force_login(self.user)

        response = self.client.post(reverse("trips:history-delete", args=[entry.pk]))

        self.assertRedirects(response, reverse("trips:trip-list"))
        self.assertFalse(TravelHistoryEntry.objects.filter(pk=entry.pk).exists())

    def test_cannot_delete_another_users_entry(self):
        entry = TravelHistoryEntry.objects.create(
            user=self.other_user, destination=self.destination
        )
        self.client.force_login(self.user)

        response = self.client.post(reverse("trips:history-delete", args=[entry.pk]))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(TravelHistoryEntry.objects.filter(pk=entry.pk).exists())
