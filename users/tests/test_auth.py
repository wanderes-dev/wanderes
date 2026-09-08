from urllib.parse import quote

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

    def test_register_redirects_to_next_when_present_and_safe(self):
        # 2026-09-09: an anonymous "Save this trip" click hits
        # trip_create's @login_required redirect to
        # /users/login/?next=/trips/create/?destination=<slug> - if the
        # visitor then chooses "Create an account" instead of logging in,
        # that same ?next= must survive registration too, or the
        # destination they were trying to save silently gets lost and
        # they land on a generic account page instead. Previously
        # register() always redirected to users:account regardless of
        # ?next=.
        next_url = "/trips/create/?destination=lisbon-pt"
        response = self.client.post(
            f"{reverse('users:register')}?next={next_url}",
            {
                "email": "newtraveler@example.com",
                "password1": "a-strong-password-123",
                "password2": "a-strong-password-123",
            },
        )

        self.assertRedirects(response, next_url, fetch_redirect_response=False)

    def test_register_ignores_unsafe_next(self):
        # An attacker-controlled ?next= pointing at an external host must
        # never be honored - same open-redirect guard Django's own
        # LoginView already applies (url_has_allowed_host_and_scheme).
        response = self.client.post(
            f"{reverse('users:register')}?next=https://evil.example.com/steal",
            {
                "email": "newtraveler@example.com",
                "password1": "a-strong-password-123",
                "password2": "a-strong-password-123",
            },
        )

        self.assertRedirects(response, reverse("users:account"))


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


class NextParamCrossLinkTests(TestCase):
    """2026-09-09: the login<->register cross-links ("New to Wanderes?
    Create an account" / "Already have an account? Log in") must forward
    ?next= too, or a visitor who arrives via trip_create's login-required
    redirect loses their destination the moment they switch from one
    form to the other - the same gap register()'s own redirect just had,
    one hop earlier."""

    def test_login_page_forwards_next_to_register_link(self):
        next_url = "/trips/create/?destination=lisbon-pt"
        # Matches the {{ request.GET.next|urlencode }} template filter's
        # default safe="/" behavior exactly - "/" stays literal, "?"/"="
        # get percent-encoded.
        encoded_next = quote(next_url, safe="/")

        response = self.client.get(f"{reverse('users:login')}?next={next_url}")

        self.assertContains(
            response, f'href="{reverse("users:register")}?next={encoded_next}"'
        )

    def test_register_page_forwards_next_to_login_link(self):
        next_url = "/trips/create/?destination=lisbon-pt"
        encoded_next = quote(next_url, safe="/")

        response = self.client.get(f"{reverse('users:register')}?next={next_url}")

        self.assertContains(response, f'href="{reverse("users:login")}?next={encoded_next}"')

    def test_login_page_without_next_renders_plain_register_link(self):
        response = self.client.get(reverse("users:login"))

        self.assertContains(response, f'href="{reverse("users:register")}"')


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
