from django.test import TestCase
from django.urls import reverse
from django.utils.translation import activate, deactivate


class LanguageSwitcherTests(TestCase):
    """2026-09-04, direct user request: "quero que vc coloque traduçao na
    pagina para EN / PT / ES / DE / IT / FR". The switcher posts to
    Django's own set_language view (django.conf.urls.i18n), which sets a
    cookie LocaleMiddleware then reads on every later request."""

    def test_switcher_lists_all_six_languages_by_native_name(self):
        response = self.client.get("/")

        content = response.content.decode()
        for name in ["English", "Português", "Español", "Deutsch", "Italiano", "Français"]:
            self.assertIn(name, content)

    def test_switching_to_portuguese_changes_rendered_content(self):
        self.client.post(reverse("set_language"), {"language": "pt", "next": "/"})

        response = self.client.get("/")

        self.assertContains(response, "Diga-nos o que você procura")

    def test_switching_to_german_changes_the_chat_page(self):
        self.client.post(reverse("set_language"), {"language": "de", "next": "/chat/"})

        response = self.client.get("/chat/")

        self.assertContains(response, "Chatte mit Wander")

    def test_html_lang_attribute_reflects_active_language(self):
        self.client.post(reverse("set_language"), {"language": "fr", "next": "/"})

        response = self.client.get("/")

        self.assertContains(response, '<html lang="fr">')

    def test_default_language_is_english(self):
        response = self.client.get("/")

        self.assertContains(response, "Tell us what you're looking for")


class TranslationCoverageTests(TestCase):
    """Confirms the compiled .mo catalogs actually contain real
    translations (not just registered as available languages with empty
    msgstr) for a representative sample spanning templates, form labels,
    and model choice labels - the three different places strings were
    wrapped in this pass."""

    def tearDown(self):
        deactivate()

    def test_representative_strings_are_translated_in_every_language(self):
        from django.utils.translation import gettext as _

        samples = {
            "pt": ("Log in", "Entrar"),
            "es": ("Log in", "Iniciar sesión"),
            "de": ("Log in", "Anmelden"),
            "it": ("Log in", "Accedi"),
            "fr": ("Log in", "Se connecter"),
        }
        for lang, (source, expected) in samples.items():
            activate(lang)
            self.assertEqual(_(source), expected)

    def test_model_choice_labels_are_translated(self):
        from django.utils.translation import gettext as _

        activate("pt")
        self.assertEqual(_("Beach"), "Praia")
        self.assertEqual(_("Very low"), "Muito baixo")
