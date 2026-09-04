from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse

from core.context_processors import _browser_preferred_language

User = get_user_model()

# Real, already-translated strings (locale/*/LC_MESSAGES/django.po) used
# throughout this file to assert "the page actually rendered in language
# X" without depending on any one page's specific copy - "Log in" is a
# simple label present on /users/login/ in every supported language,
# proven translated by core/tests/test_i18n.py's
# TranslationCoverageTests.
LOG_IN_LABEL_BY_LANGUAGE = {
    "en": "Log in",
    "pt": "Entrar",
    "es": "Iniciar sesión",
    "de": "Anmelden",
    "it": "Accedi",
    "fr": "Se connecter",
}


class BrowserPreferredLanguageHelperTests(TestCase):
    """Unit-level tests for core.context_processors._browser_preferred_language
    (2026-09-04, automatic language detection) - the pure Accept-Language
    parsing/matching step, isolated from the full request/response cycle
    below."""

    def setUp(self):
        self.factory = RequestFactory()

    def _browser_lang(self, header):
        request = self.factory.get("/", HTTP_ACCEPT_LANGUAGE=header)
        return _browser_preferred_language(request)

    def test_simple_supported_code(self):
        self.assertEqual(self._browser_lang("es"), "es")

    def test_portuguese_region_variants_map_to_generic_portuguese(self):
        self.assertEqual(self._browser_lang("pt-PT,pt;q=0.9"), "pt")
        self.assertEqual(self._browser_lang("pt-BR,pt;q=0.9"), "pt")

    def test_spanish_region_variant_maps_to_generic_spanish(self):
        self.assertEqual(self._browser_lang("es-MX,es;q=0.9,en;q=0.8"), "es")

    def test_french_region_variant_maps_to_generic_french(self):
        self.assertEqual(self._browser_lang("fr-CA,fr;q=0.9"), "fr")

    def test_german_region_variant_maps_to_generic_german(self):
        self.assertEqual(self._browser_lang("de-AT,de;q=0.9"), "de")

    def test_unsupported_language_falls_through_to_a_later_supported_one(self):
        self.assertEqual(self._browser_lang("ja,ja-JP;q=0.9,es;q=0.5"), "es")

    def test_entirely_unsupported_language_returns_none(self):
        self.assertIsNone(self._browser_lang("ja,ja-JP;q=0.9"))

    def test_missing_header_returns_none(self):
        self.assertIsNone(self._browser_lang(""))


class BrowserLanguageAutoAppliesOnFirstVisitTests(TestCase):
    """Priority 3 ("Browser language") - with no saved preference at all
    (no cookie, no account), Django's own LocaleMiddleware already applies
    the browser's Accept-Language automatically, and no code from this
    feature is needed for that to work. These tests document/confirm
    that behavior for this project's specific supported LANGUAGES set."""

    def test_supported_browser_language_is_auto_applied(self):
        response = self.client.get(reverse("users:login"), HTTP_ACCEPT_LANGUAGE="pt")

        self.assertContains(response, LOG_IN_LABEL_BY_LANGUAGE["pt"])

    def test_portuguese_region_variants_map_to_generic_portuguese(self):
        for header in ["pt-PT,pt;q=0.9", "pt-BR,pt;q=0.9"]:
            response = self.client.get(reverse("users:login"), HTTP_ACCEPT_LANGUAGE=header)
            self.assertContains(response, LOG_IN_LABEL_BY_LANGUAGE["pt"])

    def test_other_supported_region_variants_map_to_their_generic_codes(self):
        cases = {
            "es-MX,es;q=0.9": "es",
            "fr-CA,fr;q=0.9": "fr",
            "de-AT,de;q=0.9": "de",
        }
        for header, expected_lang in cases.items():
            response = self.client.get(reverse("users:login"), HTTP_ACCEPT_LANGUAGE=header)
            self.assertContains(response, LOG_IN_LABEL_BY_LANGUAGE[expected_lang])

    def test_unsupported_browser_language_falls_back_to_english_default(self):
        response = self.client.get(
            reverse("users:login"), HTTP_ACCEPT_LANGUAGE="ja,ja-JP;q=0.9"
        )
        self.assertContains(response, LOG_IN_LABEL_BY_LANGUAGE["en"])

    def test_missing_accept_language_header_falls_back_to_english_default(self):
        response = self.client.get(reverse("users:login"))
        self.assertContains(response, LOG_IN_LABEL_BY_LANGUAGE["en"])

    def test_first_time_visitor_sees_no_language_suggestion(self):
        """No saved preference yet means active language == browser
        language automatically (the case above) - so there's nothing to
        suggest switching to."""
        response = self.client.get("/", HTTP_ACCEPT_LANGUAGE="pt")

        self.assertIsNone(response.context["language_suggestion"])


class SavedPreferencePriorityTests(TestCase):
    """Priorities 1 and 2 ("previously saved user/anonymous preference")
    must always win over priority 3 (browser language) - 2026-09-04,
    automatic language detection: "Do not override an explicit user
    choice." """

    def setUp(self):
        self.user = User.objects.create_user(
            email="lang-tester@example.com", password="testpass123"
        )

    def test_anonymous_cookie_preference_beats_a_conflicting_browser_language(self):
        self.client.post(reverse("set_language"), {"language": "es", "next": "/"})

        response = self.client.get(reverse("users:login"), HTTP_ACCEPT_LANGUAGE="pt")

        self.assertContains(response, LOG_IN_LABEL_BY_LANGUAGE["es"])

    def test_authenticated_preference_beats_browser_language_on_a_fresh_client(self):
        """Simulates the same account on a different device/browser: no
        django_language cookie at all (a fresh test Client has none), but
        the account's own saved preferred_language must still win over
        whatever that new browser's Accept-Language says."""
        self.user.preferred_language = "de"
        self.user.save(update_fields=["preferred_language"])
        self.client.force_login(self.user)

        response = self.client.get(reverse("users:login"), HTTP_ACCEPT_LANGUAGE="pt")

        self.assertContains(response, LOG_IN_LABEL_BY_LANGUAGE["de"])

    def test_authenticated_preference_beats_browser_language_even_when_both_are_supported(self):
        """The explicit "browser vs. saved preference conflict" case -
        both 'it' (saved) and 'fr' (browser) are fully supported
        languages; the saved, explicit choice must still win."""
        self.user.preferred_language = "it"
        self.user.save(update_fields=["preferred_language"])
        self.client.force_login(self.user)

        response = self.client.get(reverse("users:login"), HTTP_ACCEPT_LANGUAGE="fr")

        self.assertContains(response, LOG_IN_LABEL_BY_LANGUAGE["it"])

    def test_authenticated_user_without_a_saved_preference_still_gets_browser_detection(self):
        """A blank preferred_language (the default) must not block normal
        cookie/Accept-Language detection for an authenticated visitor who
        simply hasn't made an explicit choice yet."""
        self.client.force_login(self.user)

        response = self.client.get(reverse("users:login"), HTTP_ACCEPT_LANGUAGE="es")

        self.assertContains(response, LOG_IN_LABEL_BY_LANGUAGE["es"])


class LanguageSuggestionTests(TestCase):
    """The subtle "prefer Wanderes in X?" suggestion (2026-09-04) - only
    ever a suggestion, never an automatic switch, and only ever shown
    when there's a genuine mismatch between the browser's own signal and
    the language actually being shown."""

    def setUp(self):
        self.user = User.objects.create_user(email="suggest@example.com", password="testpass123")

    def test_suggestion_appears_when_authenticated_preference_differs_from_browser(self):
        self.user.preferred_language = "en"
        self.user.save(update_fields=["preferred_language"])
        self.client.force_login(self.user)

        response = self.client.get("/", HTTP_ACCEPT_LANGUAGE="pt")

        self.assertEqual(
            response.context["language_suggestion"], {"code": "pt", "name": "Português"}
        )

    def test_suggestion_appears_when_anonymous_cookie_differs_from_browser(self):
        self.client.post(reverse("set_language"), {"language": "en", "next": "/"})

        response = self.client.get("/", HTTP_ACCEPT_LANGUAGE="es")

        self.assertEqual(response.context["language_suggestion"], {"code": "es", "name": "Español"})

    def test_no_suggestion_when_active_language_already_matches_browser(self):
        self.user.preferred_language = "pt"
        self.user.save(update_fields=["preferred_language"])
        self.client.force_login(self.user)

        response = self.client.get("/", HTTP_ACCEPT_LANGUAGE="pt")

        self.assertIsNone(response.context["language_suggestion"])

    def test_no_suggestion_for_an_unsupported_browser_language(self):
        self.user.preferred_language = "en"
        self.user.save(update_fields=["preferred_language"])
        self.client.force_login(self.user)

        response = self.client.get("/", HTTP_ACCEPT_LANGUAGE="ja,ja-JP;q=0.9")

        self.assertIsNone(response.context["language_suggestion"])

    def test_no_suggestion_after_explicitly_switching_to_the_suggested_language(self):
        """"If the user selects a language: ... do not ask again
        unnecessarily." Once the visitor accepts the suggestion (POSTs to
        set_language), the same browser Accept-Language header that
        originally caused the mismatch no longer produces one, since the
        active language now matches it."""
        self.user.preferred_language = "en"
        self.user.save(update_fields=["preferred_language"])
        self.client.force_login(self.user)
        self.assertIsNotNone(
            self.client.get("/", HTTP_ACCEPT_LANGUAGE="pt").context["language_suggestion"]
        )

        self.client.post(
            reverse("set_language"), {"language": "pt", "next": "/"}, HTTP_ACCEPT_LANGUAGE="pt"
        )

        response = self.client.get("/", HTTP_ACCEPT_LANGUAGE="pt")
        self.assertIsNone(response.context["language_suggestion"])


class SetLanguagePersistsAuthenticatedPreferenceTests(TestCase):
    """core.views.set_language (2026-09-04) - wraps Django's own
    django.views.i18n.set_language to also persist an authenticated
    visitor's explicit choice to their account, so it's respected on any
    device from then on (priority 1)."""

    def setUp(self):
        self.user = User.objects.create_user(email="persist@example.com", password="testpass123")

    def test_authenticated_switch_persists_to_the_account(self):
        self.client.force_login(self.user)

        self.client.post(reverse("set_language"), {"language": "fr", "next": "/"})

        self.user.refresh_from_db()
        self.assertEqual(self.user.preferred_language, "fr")

    def test_anonymous_switch_does_not_touch_any_account(self):
        response = self.client.post(reverse("set_language"), {"language": "fr", "next": "/"})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(User.objects.filter(preferred_language="fr").count(), 0)

    def test_invalid_language_code_is_not_persisted(self):
        self.client.force_login(self.user)

        self.client.post(reverse("set_language"), {"language": "not-a-real-language", "next": "/"})

        self.user.refresh_from_db()
        self.assertEqual(self.user.preferred_language, "")

    def test_switch_still_sets_the_cookie_exactly_as_djangos_own_view_does(self):
        """Confirms the wrapper didn't lose any of Django's own behavior
        while adding the account-persistence side effect."""
        self.client.force_login(self.user)

        response = self.client.post(reverse("set_language"), {"language": "de", "next": "/"})

        self.assertEqual(response.cookies["django_language"].value, "de")
