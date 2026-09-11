import json

from django.conf import settings
from django.utils.translation import get_language, get_supported_language_variant
from django.utils.translation import gettext as _
from django.utils.translation.trans_real import parse_accept_lang_header

# Maps each supported LANGUAGES code to the full language_TERRITORY form
# the Open Graph og:locale property expects - Django's own
# LANGUAGE_CODE/get_language() only return the bare code (e.g. "pt"),
# which isn't valid per the OG spec on its own. Territory picked to match
# this app's actual audience for each language rather than an arbitrary
# default (pt -> Brazil, given this project's working-language history,
# not just "any Portuguese").
OG_LOCALE_BY_LANGUAGE = {
    "en": "en_US",
    "pt": "pt_BR",
    "es": "es_ES",
    "de": "de_DE",
    "it": "it_IT",
    "fr": "fr_FR",
}


def _browser_preferred_language(request):
    """The best supported language the browser's own Accept-Language
    header asks for, ignoring any cookie/account override entirely.
    Deliberately separate from the *active* language (get_language()):
    the two can only ever differ when an explicit preference (anonymous
    cookie or users.User.preferred_language) already overrode the
    browser's own signal - exactly the situation worth a subtle
    suggestion.

    Reuses Django's own Accept-Language parsing/matching
    (parse_accept_lang_header + get_supported_language_variant) - the
    same functions LocaleMiddleware itself calls internally when there's
    no cookie yet - rather than re-parsing the header by hand, so
    "supported language" always means exactly what LANGUAGES/LOCALE_PATHS
    already define. trans_real is technically a private submodule, but
    parse_accept_lang_header has no public equivalent and is what
    LocaleMiddleware's own get_language_from_request relies on."""
    header = request.META.get("HTTP_ACCEPT_LANGUAGE", "")
    for accept_lang, _priority in parse_accept_lang_header(header):
        if accept_lang == "*":
            continue
        try:
            return get_supported_language_variant(accept_lang)
        except LookupError:
            continue
    return None


def language_suggestion(request):
    """A subtle "prefer Wanderes in <language>?" suggestion signal - None
    unless the browser's own Accept-Language genuinely disagrees with the
    language actually being shown right now. That only happens when an
    explicit preference (anonymous django_language cookie, or an
    authenticated user's saved preferred_language - see
    core.middleware.UserLanguagePreferenceMiddleware) already overrode
    the browser's signal: a first-time visitor with no saved preference
    at all already sees their browser's language automatically (via
    Django's own LocaleMiddleware, no code needed here), so no suggestion
    is ever shown to them - only to a *returning* visitor whose saved
    choice and current browser now disagree (e.g. shared/borrowed device,
    changed OS/browser language since). Deliberately never overrides the
    active language itself - templates/base.html only ever renders this
    as a dismissible suggestion, never an automatic switch."""
    browser_lang = _browser_preferred_language(request)
    active_lang = get_language()
    if not browser_lang or browser_lang == active_lang:
        return {"language_suggestion": None}
    return {
        "language_suggestion": {
            "code": browser_lang,
            "name": dict(settings.LANGUAGES).get(browser_lang, browser_lang),
        }
    }


def site_meta(request):
    """Canonical-URL and structured-data context for every template.

    canonical_url is built from settings.SITE_DOMAIN, never from
    request.get_host() - the live service is reachable under more than
    one hostname (see CanonicalDomainRedirectMiddleware's docstring), and
    a canonical link that echoed back whatever host served the request
    would defeat its own purpose.

    organization_jsonld is serialized here with json.dumps rather than
    hand-written inline in the template with {% trans %} calls mixed in -
    Django's default autoescaping (meant for HTML) would otherwise apply
    to content sitting inside a <script> tag, the wrong escaping entirely
    for JSON. Every value here is a fixed, translated string this app
    controls - nothing user-supplied ever reaches it - so rendering the
    result with |safe in the template is fine."""
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
    # SOCIALACCOUNT_PROVIDERS always registers the google provider (see
    # settings/base.py), but with no real GOOGLE_OAUTH_CLIENT_ID/SECRET
    # set, allauth's own {% get_providers %} tag still lists it - the
    # button would render and redirect to Google with an empty client_id,
    # which Google rejects with its own error page. This flag lets
    # templates show the button only once real credentials actually
    # exist, rather than shipping a visibly broken one.
    google_app = settings.SOCIALACCOUNT_PROVIDERS.get("google", {}).get("APP", {})
    google_oauth_configured = bool(google_app.get("client_id"))
    return {
        "site_domain": settings.SITE_DOMAIN,
        "canonical_url": f"https://{settings.SITE_DOMAIN}{request.path}",
        "organization_jsonld": organization_jsonld,
        "google_oauth_configured": google_oauth_configured,
        # Same reasoning as google_oauth_configured above, for password
        # reset via emailed token. Checks EMAIL_BACKEND, not EMAIL_HOST
        # directly - EMAIL_HOST alone has a real default now, so
        # base.py's own EMAIL_HOST/EMAIL_HOST_USER-gated backend choice
        # is the actual signal for whether real credentials exist.
        # Console backend means a reset "succeeds" but delivers nothing
        # anyone can see, so the "Forgot your password?" link stays
        # hidden until then.
        "email_configured": settings.EMAIL_BACKEND == "django.core.mail.backends.smtp.EmailBackend",
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
