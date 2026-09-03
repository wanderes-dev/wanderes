from django.conf import settings
from django.http import HttpResponsePermanentRedirect

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
CANONICAL_REDIRECT_HOSTS = frozenset(
    {
        "www.wanderes.com",
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
