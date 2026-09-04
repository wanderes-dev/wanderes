import re

from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from users.models import User

_SMTP_SETTINGS = {"EMAIL_HOST": "smtp.example.com"}


class ForgotPasswordLinkVisibilityTests(TestCase):
    """Mirrors the google_oauth_configured pattern (users/tests/
    test_google_oauth.py) - the link must never render until real SMTP
    credentials exist, since the console-backend fallback "succeeds"
    without ever actually delivering anything a visitor could see."""

    def test_link_hidden_on_login_page_without_real_email_credentials(self):
        response = self.client.get(reverse("users:login"))

        self.assertNotContains(response, "Forgot your password?")

    @override_settings(**_SMTP_SETTINGS)
    def test_link_shown_on_login_page_once_email_is_configured(self):
        response = self.client.get(reverse("users:login"))

        self.assertContains(response, "Forgot your password?")
        self.assertContains(response, reverse("users:password_reset"))


class PasswordResetFlowTests(TestCase):
    """End-to-end coverage of Django's built-in reset views wired up
    under the users: namespace (2026-09-04) - the real risk here was
    never the view logic itself (Django's own, well-tested), but getting
    the namespaced success_url/email-link reversal wrong, which would
    have 404ed silently instead of erroring loudly."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="reset-flow@example.com", password="old-password-123"
        )

    def test_requesting_a_reset_always_redirects_to_the_done_page(self):
        # Same response whether the email exists or not - Django's own
        # security convention, never confirm/deny account existence.
        for email in ["reset-flow@example.com", "no-such-account@example.com"]:
            response = self.client.post(
                reverse("users:password_reset"), {"email": email}
            )
            self.assertRedirects(response, reverse("users:password_reset_done"))

    def test_reset_email_is_sent_with_a_working_link(self):
        self.client.post(
            reverse("users:password_reset"), {"email": "reset-flow@example.com"}
        )

        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(email.subject, "Reset your Wanderes password")
        self.assertIn("reset-flow@example.com", email.to)

        match = re.search(r"https?://[^/]+(/users/reset/\S+/)", email.body)
        self.assertIsNotNone(match, f"no reset link found in email body: {email.body!r}")
        reset_path = match.group(1)

        # Following the link and setting a new password should actually
        # work end to end, not just resolve.
        confirm_response = self.client.get(reset_path, follow=True)
        self.assertContains(confirm_response, "Set a new password")

        # Django's PasswordResetConfirmView stores the validated token in
        # the session and swaps the URL's real token for "set-password" on
        # first GET - post to that redirected URL, not the emailed one.
        set_password_url = confirm_response.redirect_chain[-1][0]
        post_response = self.client.post(
            set_password_url,
            {"new_password1": "brand-new-password-456", "new_password2": "brand-new-password-456"},
        )
        self.assertRedirects(post_response, reverse("users:password_reset_complete"))

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("brand-new-password-456"))

    def test_email_uses_the_canonical_site_domain_not_the_request_host(self):
        # The reset link's domain comes from django.contrib.sites's Site
        # row (kept in sync with settings.SITE_DOMAIN), not
        # request.get_host() - matters because the live service is
        # reachable under more than one hostname (see
        # core.middleware.CanonicalDomainRedirectMiddleware).
        self.client.post(
            reverse("users:password_reset"),
            {"email": "reset-flow@example.com"},
            HTTP_HOST="testserver",
        )

        self.assertIn("www.wanderes.com", mail.outbox[0].body)

    def test_invalid_or_reused_token_shows_the_link_expired_state(self):
        uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))
        response = self.client.get(
            reverse(
                "users:password_reset_confirm",
                kwargs={"uidb64": uidb64, "token": "not-a-real-token"},
            ),
            follow=True,
        )

        self.assertContains(response, "This reset link no longer works")
        self.assertContains(response, reverse("users:password_reset"))

    def test_a_used_token_cannot_be_reused(self):
        token = default_token_generator.make_token(self.user)
        uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))
        confirm_url = reverse(
            "users:password_reset_confirm", kwargs={"uidb64": uidb64, "token": token}
        )

        first = self.client.get(confirm_url, follow=True)
        set_password_url = first.redirect_chain[-1][0]
        self.client.post(
            set_password_url,
            {
                "new_password1": "another-new-password-789",
                "new_password2": "another-new-password-789",
            },
        )

        # A fresh client (no session state from the first attempt) trying
        # the original emailed link again must be rejected.
        second_client_response = self.client_class().get(confirm_url, follow=True)
        self.assertContains(second_client_response, "This reset link no longer works")
