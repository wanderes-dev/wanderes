from django.test import TestCase

from users.models import TravelerProfile, User


class UserManagerTests(TestCase):
    def test_create_user_with_email(self):
        user = User.objects.create_user(email="traveler@example.com", password="testpass123")

        self.assertEqual(user.email, "traveler@example.com")
        self.assertTrue(user.check_password("testpass123"))
        self.assertFalse(user.is_staff)

    def test_create_superuser_with_email(self):
        admin = User.objects.create_superuser(email="admin@example.com", password="testpass123")

        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)

    def test_create_user_without_email_raises(self):
        with self.assertRaises(ValueError):
            User.objects.create_user(email="", password="testpass123")


class TravelerProfileTests(TestCase):
    def test_profile_links_to_user(self):
        user = User.objects.create_user(email="traveler@example.com", password="testpass123")
        profile = TravelerProfile.objects.create(
            user=user, preferred_trip_types=["beach", "culture"], preferred_cost_of_living=3
        )

        self.assertEqual(profile.user, user)
        self.assertEqual(user.traveler_profile, profile)
