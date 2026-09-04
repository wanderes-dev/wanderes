from django.conf import settings
from django.http import HttpResponsePermanentRedirect
from django.utils import translation

# Known aliases of the live service that should never accumulate their own
# search-ranking signal separately from SITE_DOMAIN (2026-09-03, SEO prep -
# see PROJECT_STATE.md's Phase 18 entries for how each of these came to
# exist). Deliberately an explicit, hand-maintained list rather than "any
# host that isn't SITE_DOMAIN" - Render assigns the live service its own
# current onrender.com hostname (currently wanderes-web.onrender.com) and
# very likely uses that same hostname for its own healthCheckPath probe
# (render.yaml); blanket-redirecting every non-canonical host would risk
# redirecting that health check too, which Render would read as the
# service being down. Add a new alias here only once it's confirmed to be
# a public-facing duplicate, never Render's own current service hostname.
#
# www.wanderes.com is deliberately NOT in this list, even though it looks
# like the obvious "other" alias to consolidate (2026-09-03 production
# incident, same day as this file's introduction): something outside this
# app - Render's own domain config or DNS, confirmed empirically since
# nothing in this codebase does it - already redirects the bare apex
# wanderes.com to www.wanderes.com. Adding www.wanderes.com here on top of
# that created an infinite apex->www->apex redirect loop, taking the
# entire public site down (ERR_TOO_MANY_REDIRECTS) for several minutes
# before being caught and reverted. SITE_DOMAIN is now www.wanderes.com to
# match that reality instead of fighting it - never re-add www.wanderes.com
# here without first confirming, live, that nothing upstream still
# redirects apex to www.
CANONICAL_REDIRECT_HOSTS = frozenset(
    {
        "travelagent-web.onrender.com",
    }
)


class CanonicalDomainRedirectMiddleware:
    """301-redirects a small, explicit set of known duplicate hostnames to
    settings.SITE_DOMAIN, so Google consolidates ranking signal onto one
    URL per page instead of splitting it across www/apex/legacy-domain
    copies of the same content. /health/ is always exempted regardless of
    host - a health check must never receive a redirect instead of a 200,
    on any hostname, or Render would read the service as down."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == "/health/":
            return self.get_response(request)

        host = request.get_host().split(":")[0].lower()
        if host in CANONICAL_REDIRECT_HOSTS:
            target = f"https://{settings.SITE_DOMAIN}{request.get_full_path()}"
            return HttpResponsePermanentRedirect(target)

        return self.get_response(request)


class UserLanguagePreferenceMiddleware:
    """Makes an authenticated user's saved language (users.User.
    preferred_language) win over whatever LocaleMiddleware already picked
    from the anonymous django_language cookie or the browser's
    Accept-Language header (2026-09-04, automatic language detection -
    priority 1, "previously saved user language preference... always
    respect it," regardless of which device/browser they're on right
    now). Must sit after AuthenticationMiddleware in settings.MIDDLEWARE
    (request.user isn't resolved yet before that) and after
    LocaleMiddleware (this deliberately overrides its result, not races
    it) - see the ordering comment in settings/base.py.

    A blank preferred_language (the default - no explicit choice made
    yet) is a no-op: normal cookie/Accept-Language detection applies
    exactly as it did before this middleware existed."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and user.preferred_language:
            translation.activate(user.preferred_language)
            request.LANGUAGE_CODE = translation.get_language()
        return self.get_response(request)
