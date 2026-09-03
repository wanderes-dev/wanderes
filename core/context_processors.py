import json

from django.conf import settings
from django.utils.translation import gettext as _


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
    }
