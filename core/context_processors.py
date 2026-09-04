import json

from django.conf import settings
from django.utils.translation import get_language
from django.utils.translation import gettext as _

# Maps each supported LANGUAGES code to the full language_TERRITORY form
# the Open Graph og:locale property expects (2026-09-04, translation
# rollout) - Django's own LANGUAGE_CODE/get_language() only ever return
# the bare code (e.g. "pt"), which isn't valid per the OG spec on its
# own. Territory picked to match this app's actual audience for each
# language rather than an arbitrary default (pt -> Brazil, given this
# project's own working language history, not just "any Portuguese").
OG_LOCALE_BY_LANGUAGE = {
    "en": "en_US",
    "pt": "pt_BR",
    "es": "es_ES",
    "de": "de_DE",
    "it": "it_IT",
    "fr": "fr_FR",
}


def site_meta(request):
    """Canonical-URL and structured-data context for every template
    (2026-09-03, SEO prep).

    canonical_url is built from settings.SITE_DOMAIN, never from
    request.get_host() - the live service is reachable under more than
    one hostname (see CanonicalDomainRedirectMiddleware's docstring), and
    a canonical link that echoed back whatever host served the request
    would defeat its own purpose.

    organization_jsonld is serialized here with json.dumps rather than
    hand-written inline in the template with {% trans %} calls mixed in -
    Django's default autoescaping (meant for HTML) would otherwise apply
    to content sitting inside a <script> tag, which is the wrong escaping
    entirely for JSON. Every value here is a fixed, translated string this
    app controls - nothing user-supplied ever reaches it - so rendering
    the result with |safe in the template is fine."""
    organization_jsonld = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "Organization",
            "name": "Wanderes",
            "url": f"https://{settings.SITE_DOMAIN}/",
            "description": _(
                "Wanderes is an intelligent travel consultant that recommends real "
                "destinations based on what travelers actually want."
            ),
        }
    )
    # Same escaping Django's own json_script helper applies - none of the
    # fixed values above contain these characters today, but a translator
    # could plausibly introduce one in a future locale's .po file, and an
    # unescaped "<" would let translated text break out of the <script>
    # tag it's embedded in.
    organization_jsonld = (
        organization_jsonld.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    )
    # 2026-09-03, Google OAuth login prep: SOCIALACCOUNT_PROVIDERS always
    # registers the google provider (see settings/base.py), but with no
    # real GOOGLE_OAUTH_CLIENT_ID/SECRET set yet, allauth's own
    # {% get_providers %} tag still lists it - the button would render and
    # redirect to Google with an empty client_id, which Google rejects
    # with its own error page. This flag lets templates show the button
    # only once real credentials actually exist, rather than shipping a
    # visibly broken button in the meantime.
    google_app = settings.SOCIALACCOUNT_PROVIDERS.get("google", {}).get("APP", {})
    google_oauth_configured = bool(google_app.get("client_id"))
    return {
        "site_domain": settings.SITE_DOMAIN,
        "canonical_url": f"https://{settings.SITE_DOMAIN}{request.path}",
        "organization_jsonld": organization_jsonld,
        "google_oauth_configured": google_oauth_configured,
        # 2026-09-04, password reset via emailed token: same reasoning as
        # google_oauth_configured above - EMAIL_HOST unset means the
        # console backend is in effect (reset "succeeds" but delivers
        # nothing anyone can see), so the "Forgot your password?" link
        # stays hidden until real SMTP credentials exist.
        "email_configured": bool(settings.EMAIL_HOST),
        "og_locale": OG_LOCALE_BY_LANGUAGE.get(get_language(), "en_US"),
        # Raw settings.LANGUAGES, deliberately not Django's own
        # {% get_available_languages %} template tag - that tag runs each
        # name through gettext(), which would translate "Português" into
        # whatever word the *currently active* language uses for
        # Portuguese (e.g. "Portugiesisch" while browsing in German)
        # instead of leaving it as its own native name - the whole point
        # of showing native names in the switcher is so a reader can find
        # their language without first being able to read the active one.
        "available_languages": settings.LANGUAGES,
    }
