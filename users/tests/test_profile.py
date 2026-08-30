from django.test import TestCase
from django.urls import reverse

from analytics.models import Event
from users.models import TravelerProfile, User


class TravelerProfileViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="traveler@example.com", password="testpass123")

    def test_profile_requires_login(self):
        response = self.client.get(reverse("users:profile"))

        self.assertRedirects(response, f"{reverse('users:login')}?next={reverse('users:profile')}")

    def test_get_profile_creates_one_if_missing(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("users:profile"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(TravelerProfile.objects.filter(user=self.user).exists())

    def test_post_updates_profile(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("users:profile"),
            {"preferred_trip_types": ["beach", "culture"], "preferred_cost_of_living": 3},
        )

        self.assertRedirects(response, reverse("users:profile"))
        profile = TravelerProfile.objects.get(user=self.user)
        self.assertEqual(profile.preferred_trip_types, ["beach", "culture"])
        self.assertEqual(profile.preferred_cost_of_living, 3)
        self.assertTrue(
            Event.objects.filter(user=self.user, event_type="profile_completed").exists()
        )

    def test_profile_completed_only_recorded_once(self):
        self.client.force_login(self.user)
        self.client.post(
            reverse("users:profile"),
            {"preferred_trip_types": ["beach"], "preferred_cost_of_living": 2},
        )

        self.client.post(
            reverse("users:profile"),
            {"preferred_trip_types": ["beach", "nature"], "preferred_cost_of_living": 2},
        )

        self.assertEqual(
            Event.objects.filter(user=self.user, event_type="profile_completed").count(), 1
        )

    def test_empty_profile_save_does_not_record_profile_completed(self):
        self.client.force_login(self.user)

        self.client.post(reverse("users:profile"), {"preferred_trip_types": []})

        self.assertFalse(
            Event.objects.filter(user=self.user, event_type="profile_completed").exists()
        )

    def test_users_cannot_affect_each_others_profile(self):
        other_user = User.objects.create_user(email="other@example.com", password="testpass123")
        TravelerProfile.objects.create(
            user=other_user, preferred_trip_types=["nature"], preferred_cost_of_living=5
        )

        self.client.force_login(self.user)
        self.client.post(
            reverse("users:profile"),
            {"preferred_trip_types": ["city"], "preferred_cost_of_living": 1},
        )

        other_profile = TravelerProfile.objects.get(user=other_user)
        self.assertEqual(other_profile.preferred_trip_types, ["nature"])
        self.assertEqual(other_profile.preferred_cost_of_living, 5)
