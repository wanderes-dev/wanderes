import logging

from django.conf import settings
from django.db import connections
from django.db.utils import OperationalError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.urls import reverse

from travel.models import Destination

logger = logging.getLogger(__name__)

# The full set of genuinely public, content-bearing pages worth telling
# search engines about (2026-09-03, SEO prep) - drives sitemap.xml. Every
# other route either needs a login (account/profile/trips - real SEO value
# there is zero, and a crawler would just hit the login redirect), is an
# API endpoint, or is /admin/ - none of those belong in a sitemap.
# register/login are deliberately left out too: they're thin, duplicate-ish
# form pages with no unique content to rank on, though nothing stops a
# crawler that finds them via the nav from indexing them (robots.txt
# doesn't disallow them, only the truly private paths below).
_SITEMAP_ENTRIES = [
    {"url_name": "core:landing", "changefreq": "weekly", "priority": "1.0"},
    {"url_name": "ai:chat", "changefreq": "weekly", "priority": "0.9"},
]


def landing(request):
    """Marketing/entry page at the bare domain root.

    2026-09-01, direct user request: "nao caia direto no chat" - a
    first-time visitor should land somewhere that explains the product
    before being dropped into the chat, not be redirected straight to
    /chat/ (the previous behavior, added right after the first Phase 18
    deploy just to avoid a 404 - see DEVELOPMENT_LOG.md). The destination
    teaser below uses real curated Destination rows, never invented
    copy - `05_AI_DESIGN.md` §7's "never invent travel data" principle
    applies to product marketing surfaces too, not just AI replies.
    """
    featured_destinations = Destination.objects.order_by("id")[:3]
    # A single example destination for the "see it in action" product
    # preview (2026-09-01, second UX pass, §4: "show the product, not
    # just describe it") - reuses the exact same .chat-bubble/
    # .recommendation-card markup as the real chat page, so this is a
    # real product screenshot in spirit, not a disconnected mockup. Picks
    # a beach/nature destination specifically since that's what the
    # accompanying example message describes - falls back to whatever
    # exists if the curated set ever stops including one.
    preview_destination = (
        Destination.objects.filter(trip_type__in=["beach", "nature"]).order_by("id").first()
        or Destination.objects.order_by("id").first()
    )
    return render(
        request,
        "core/landing.html",
        {
            "featured_destinations": featured_destinations,
            "preview_destination": preview_destination,
        },
    )


def health_check(request):
    """Report application health, including critical infrastructure.

    Milestone 1 (04_MVP_IMPLEMENTATION_PLAN.md) requires a basic health
    endpoint confirming the app can reach PostgreSQL. Redis and other
    dependencies can be added here as they become part of the request path.
    """
    database_ok = _database_is_reachable()
    status = "ok" if database_ok else "degraded"
    payload = {
        "status": status,
        "database": "ok" if database_ok else "unavailable",
    }
    return JsonResponse(payload, status=200 if database_ok else 503)


def _database_is_reachable():
    try:
        connections["default"].cursor()
        return True
    except OperationalError:
        # Never swallow this silently - the real driver error (bad host,
        # SSL requirement, connection limit, etc.) is exactly what's needed
        # to diagnose a real "database unavailable" incident, and it was
        # previously only visible as a generic 503 in the access log.
        logger.error("Database health check failed.", exc_info=True)
        return False


def robots_txt(request):
    """Tells crawlers what's actually worth indexing (2026-09-03, SEO
    prep). Disallows only genuinely private, login-gated, or non-content
    paths - a crawler hitting one of these unauthenticated would just find
    a login redirect or raw JSON, neither of which is worth indexing.
    Points at sitemap.xml using SITE_DOMAIN, never request.get_host(), for
    the same duplicate-hostname reason as everywhere else in this pass."""
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /admin/",
        "Disallow: /users/account/",
        "Disallow: /users/profile/",
        "Disallow: /trips/",
        "Disallow: /api/",
        "Disallow: /health/",
        "",
        f"Sitemap: https://{settings.SITE_DOMAIN}{reverse('core:sitemap')}",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


def sitemap_xml(request):
    """A hand-written sitemap rather than django.contrib.sitemaps
    (2026-09-03, SEO prep) - with only two genuinely public pages right
    now, the framework's extra moving parts (django.contrib.sites,
    per-model Sitemap classes) aren't worth it, and its default URL
    generation reads the domain off the incoming request/Site object -
    exactly the duplicate-hostname problem SITE_DOMAIN exists to avoid.
    Revisit if/when the app gains real per-destination pages worth
    listing individually."""
    urls = "".join(
        f"<url><loc>https://{settings.SITE_DOMAIN}{reverse(entry['url_name'])}</loc>"
        f"<changefreq>{entry['changefreq']}</changefreq>"
        f"<priority>{entry['priority']}</priority></url>"
        for entry in _SITEMAP_ENTRIES
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + urls + "</urlset>"
    )
    return HttpResponse(xml, content_type="application/xml")
