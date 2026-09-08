from django.test import TestCase
from django.urls import reverse

from travel.models import CountryEntryRequirement
from users.models import User


class CountryAdminAccessTests(TestCase):
    def setUp(self):
        self.country = CountryEntryRequirement.objects.create(country="Testland")
        self.staff_user = User.objects.create_user(
            email="staff@example.com", password="testpass123", is_staff=True
        )
        self.regular_user = User.objects.create_user(
            email="traveler@example.com", password="testpass123"
        )

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse("travel:country-list"))

        self.assertEqual(response.status_code, 302)

    def test_non_staff_user_is_redirected(self):
        self.client.force_login(self.regular_user)

        response = self.client.get(reverse("travel:country-list"))

        self.assertEqual(response.status_code, 302)

    def test_staff_user_can_access_the_list(self):
        self.client.force_login(self.staff_user)

        response = self.client.get(reverse("travel:country-list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Testland")


class CountryAdminEditTests(TestCase):
    def setUp(self):
        self.country = CountryEntryRequirement.objects.create(
            country="Testland", visa_notes="Old notes"
        )
        self.staff_user = User.objects.create_user(
            email="staff@example.com", password="testpass123", is_staff=True
        )
        self.client.force_login(self.staff_user)

    def test_create_new_country(self):
        response = self.client.post(
            reverse("travel:country-create"),
            {
                "country": "Newland",
                "visa_required_nationalities": "[]",
                "visa_notes": "",
                "vaccine_requirements": "[]",
                "other_requirements": "[]",
            },
        )

        country = CountryEntryRequirement.objects.get(country="Newland")
        self.assertRedirects(response, reverse("travel:country-edit", args=[country.pk]))

    def test_edit_updates_fields(self):
        response = self.client.post(
            reverse("travel:country-edit", args=[self.country.pk]),
            {
                "country": "Testland",
                "visa_required_nationalities": "[]",
                "visa_notes": "New notes",
                "vaccine_requirements": "[]",
                "other_requirements": "[]",
            },
        )

        self.country.refresh_from_db()
        self.assertRedirects(response, reverse("travel:country-edit", args=[self.country.pk]))
        self.assertEqual(self.country.visa_notes, "New notes")

    def test_add_video_appends_to_the_list(self):
        self.client.post(
            reverse("travel:country-add-video", args=[self.country.pk]),
            {"url": "https://www.youtube.com/watch?v=abc123", "language": "en"},
        )
        self.client.post(
            reverse("travel:country-add-video", args=[self.country.pk]),
            {"url": "https://www.youtube.com/watch?v=def456", "language": "pt"},
        )

        self.country.refresh_from_db()
        self.assertEqual(
            self.country.videos,
            [
                ["https://www.youtube.com/watch?v=abc123", "EN"],
                ["https://www.youtube.com/watch?v=def456", "PT"],
            ],
        )

    def test_remove_video_by_index(self):
        self.country.videos = [
            ["https://www.youtube.com/watch?v=abc123", "EN"],
            ["https://www.youtube.com/watch?v=def456", "PT"],
        ]
        self.country.save(update_fields=["videos"])

        self.client.post(
            reverse("travel:country-remove-video", args=[self.country.pk, 0])
        )

        self.country.refresh_from_db()
        self.assertEqual(
            self.country.videos, [["https://www.youtube.com/watch?v=def456", "PT"]]
        )

    def test_list_shows_video_count(self):
        self.country.videos = [["https://www.youtube.com/watch?v=abc123", "EN"]]
        self.country.save(update_fields=["videos"])

        response = self.client.get(reverse("travel:country-list"))

        self.assertContains(response, "1 video")
