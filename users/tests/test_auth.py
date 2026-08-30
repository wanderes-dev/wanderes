from django.test import TestCase
from django.urls import reverse

from analytics.models import Event
from users.models import User


class RegistrationTests(TestCase):
    def test_register_creates_user_and_logs_in(self):
        response = self.client.post(
            reverse("users:register"),
            {
                "email": "newtraveler@example.com",
                "password1": "a-strong-password-123",
                "password2": "a-strong-password-123",
            },
        )

        self.assertRedirects(response, reverse("users:account"))
        self.assertTrue(User.objects.filter(email="newtraveler@example.com").exists())
        self.assertTrue(response.wsgi_request.user.is_authenticated)
        user = User.objects.get(email="newtraveler@example.com")
        self.assertTrue(
            Event.objects.filter(user=user, event_type="user_registered").exists()
        )

    def test_register_rejects_mismatched_passwords(self):
        response = self.client.post(
            reverse("users:register"),
            {
                "email": "newtraveler@example.com",
                "password1": "a-strong-password-123",
                "password2": "does-not-match",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(email="newtraveler@example.com").exists())


class LoginLogoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="traveler@example.com", password="testpass123")

    def test_login_with_email(self):
        response = self.client.post(
            reverse("users:login"), {"username": "traveler@example.com", "password": "testpass123"}
        )

        self.assertRedirects(response, reverse("users:account"))

    def test_login_with_wrong_password_fails(self):
        response = self.client.post(
            reverse("users:login"), {"username": "traveler@example.com", "password": "wrongpass"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_logout(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse("users:logout"))

        self.assertRedirects(response, reverse("users:login"))
        self.assertFalse(response.wsgi_request.user.is_authenticated)


class AccountAccessTests(TestCase):
    def test_account_requires_login(self):
        response = self.client.get(reverse("users:account"))

        self.assertRedirects(response, f"{reverse('users:login')}?next={reverse('users:account')}")

    def test_account_accessible_when_logged_in(self):
        user = User.objects.create_user(email="traveler@example.com", password="testpass123")
        self.client.force_login(user)

        response = self.client.get(reverse("users:account"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "traveler@example.com")
