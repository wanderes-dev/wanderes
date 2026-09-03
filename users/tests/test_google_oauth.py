from types import SimpleNamespace

from allauth.account.signals import user_signed_up
from django.contrib.sites.models import Site
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from analytics.models import Event
from users.models import User

_CONFIGURED_PROVIDERS = {
    "google": {
        "SCOPE": ["profile", "email"],
        "AUTH_PARAMS": {"access_type": "online"},
        "APP": {"client_id": "test-client-id", "secret": "test-secret", "key": ""},
    }
}


class GoogleButtonVisibilityTests(TestCase):
    """The Google button must never render without real credentials
    configured (2026-09-03) - verified live that clicking it with an
    empty client_id redirects to Google's own "invalid_client" error
    page, which would be a broken feature shown to real visitors."""

    def test_button_hidden_on_login_page_without_real_credentials(self):
        response = self.client.get(reverse("users:login"))

        self.assertNotContains(response, "Continue with Google")

    def test_button_hidden_on_register_page_without_real_credentials(self):
        response = self.client.get(reverse("users:register"))

        self.assertNotContains(response, "Continue with Google")

    @override_settings(SOCIALACCOUNT_PROVIDERS=_CONFIGURED_PROVIDERS)
    def test_button_shown_on_login_page_once_credentials_are_configured(self):
        response = self.client.get(reverse("users:login"))

        self.assertContains(response, "Continue with Google")
        self.assertContains(response, "/accounts/google/login/")

    @override_settings(SOCIALACCOUNT_PROVIDERS=_CONFIGURED_PROVIDERS)
    def test_button_shown_on_register_page_once_credentials_are_configured(self):
        response = self.client.get(reverse("users:register"))

        self.assertContains(response, "Continue with Google")


class AllauthUrlsTests(TestCase):
    def test_google_login_url_resolves(self):
        response = self.client.get("/accounts/google/login/")

        # Not a 404 - allauth's own view handles it (redirects toward
        # Google, or errors on the empty client_id - either way, routing
        # itself works).
        self.assertNotEqual(response.status_code, 404)


class ExistingLoginStillWorksTests(TestCase):
    """Regression coverage for the real bug this change introduced and
    fixed in the same pass: adding allauth.account.auth_backends.
    AuthenticationBackend alongside ModelBackend meant login() could no
    longer infer which backend authenticated a user created directly by
    UserRegistrationForm.save() (no authenticate() call in that path) -
    users/views.py's register() now passes backend= explicitly."""

    def test_register_still_logs_the_new_user_in(self):
        response = self.client.post(
            reverse("users:register"),
            {
                "email": "still-works@example.com",
                "password1": "a-strong-password-123",
                "password2": "a-strong-password-123",
            },
        )

        self.assertRedirects(response, reverse("users:account"))
        self.assertTrue(response.wsgi_request.user.is_authenticated)

    def test_existing_email_password_login_still_works(self):
        User.objects.create_user(email="loginworks@example.com", password="a-strong-password-123")

        response = self.client.post(
            reverse("users:login"),
            {"username": "loginworks@example.com", "password": "a-strong-password-123"},
        )

        self.assertTrue(response.wsgi_request.user.is_authenticated)


class SiteDomainTests(TestCase):
    """The users.0004_configure_site_domain data migration must keep
    django.contrib.sites's Site row in sync with settings.SITE_DOMAIN -
    allauth uses this Site for parts of its own URL construction, and it
    must never silently drift back to the framework's own "example.com"
    placeholder."""

    def test_site_domain_matches_settings(self):
        from django.conf import settings

        site = Site.objects.get(id=settings.SITE_ID)

        self.assertEqual(site.domain, settings.SITE_DOMAIN)
        self.assertEqual(site.name, "Wanderes")


class SocialSignupAnalyticsTests(TestCase):
    """users.signals.track_social_signup mirrors users.views.register's
    own record_event("user_registered", ...) call for the Google path -
    allauth never touches that manual view, so there's no risk of a
    single signup being counted twice."""

    def test_records_user_registered_event_with_the_provider_as_source(self):
        user = User.objects.create_user(email="social-signup@example.com")
        request = RequestFactory().get("/accounts/google/login/callback/")
        fake_sociallogin = SimpleNamespace(account=SimpleNamespace(provider="google"))

        user_signed_up.send(
            sender=user.__class__, request=request, user=user, sociallogin=fake_sociallogin
        )

        event = Event.objects.get(user=user, event_type="user_registered")
        self.assertEqual(event.metadata, {"source": "google"})
