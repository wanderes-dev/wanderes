import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connections
from django.db.utils import OperationalError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import check_for_language
from django.views.i18n import set_language as django_set_language

from travel.models import Destination

logger = logging.getLogger(__name__)

# Genuinely public, content-bearing pages worth telling search engines
# about - feeds sitemap.xml. Everything else needs a login (account/
# profile/trips - zero real SEO value there, a crawler would just hit the
# login redirect), is an API endpoint, or is /admin/, so none of those
# belong here. register/login are left out too: thin, duplicate-ish forms
# with no unique content to rank on - robots.txt doesn't disallow them, so
# a crawler that finds them via the nav can still index them, they just
# aren't listed explicitly.
_SITEMAP_ENTRIES = [
    {"url_name": "core:landing", "changefreq": "weekly", "priority": "1.0"},
    {"url_name": "ai:chat", "changefreq": "weekly", "priority": "0.9"},
]


def landing(request):
    """Marketing/entry page at the bare domain root.

    A first-time visitor should land somewhere that explains the product
    before getting dropped into the chat, not redirected straight to
    /chat/ (the old behavior). The destination teaser below uses real
    curated Destination rows, never invented copy - `05_AI_DESIGN.md`
    §7's "never invent travel data" principle applies to marketing
    surfaces too, not just AI replies.
    """
    featured_destinations = Destination.objects.order_by("id")[:3]
    # A single example destination for the "see it in action" preview -
    # reuses the same .chat-bubble/.recommendation-card markup as the
    # real chat page, so this is a real product screenshot in spirit, not
    # a disconnected mockup. Pinned to Bali specifically rather than
    # "whatever beach/nature destination sorts first" - landing.html's
    # fit-reasons copy names Bali and its real crowd/quiet-area tradeoff
    # directly, so the destination shown must always actually be Bali,
    # not just resemble the kind of place the copy describes. Falls back
    # to the generic lookup only if the curated set ever stops including
    # Bali (e.g. an incompletely-seeded dev database).
    preview_destination = (
        Destination.objects.filter(slug="bali-id").first()
        or Destination.objects.filter(trip_type__in=["beach", "nature"]).order_by("id").first()
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


def set_language(request):
    """Wraps Django's own django.views.i18n.set_language view to also
    persist an authenticated visitor's explicit choice to their account
    (users.User.preferred_language), so it follows them to any device,
    not just the browser that set the django_language cookie. Reuses all
    of Django's own cookie-setting/redirect/referer-validation logic
    rather than reimplementing it; the only addition is the account-level
    side effect Django's own view has no concept of.

    Mirrors Django's own validation exactly (request.method == "POST" and
    check_for_language(lang_code)) rather than a separate check, so this
    only ever persists a value Django's view just accepted - never one it
    silently ignored (e.g. a POST with no or invalid `language`, which
    leaves the cookie/account untouched, per its own docstring)."""
    response = django_set_language(request)
    if request.method == "POST" and request.user.is_authenticated:
        lang_code = request.POST.get("language")
        if lang_code and check_for_language(lang_code):
            get_user_model().objects.filter(pk=request.user.pk).update(
                preferred_language=lang_code
            )
    return response


def health_check(request):
    """Report application health, including critical infrastructure.

    Confirms the app can reach PostgreSQL, per 04_MVP_IMPLEMENTATION_PLAN.md.
    Redis and other dependencies can be added here as they become part of
    the request path.
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
        # Don't swallow this silently - the real driver error (bad host,
        # SSL requirement, connection limit, etc.) is exactly what's
        # needed to diagnose a "database unavailable" incident, and
        # otherwise it's only ever visible as a generic 503 in the access
        # log.
        logger.error("Database health check failed.", exc_info=True)
        return False


def robots_txt(request):
    """Tells crawlers what's actually worth indexing. Disallows only
    genuinely private, login-gated, or non-content paths - an
    unauthenticated crawler hitting one of these would just find a login
    redirect or raw JSON, neither worth indexing. Points at sitemap.xml
    using SITE_DOMAIN, never request.get_host(), for the same
    duplicate-hostname reason as everywhere else here."""
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /admin/",
        "Disallow: /users/account/",
        "Disallow: /users/profile/",
        "Disallow: /trips/",
        "Disallow: /api/",
        "Disallow: /health/",
        # /travel/ only ever holds the staff-only country-videos editing
        # tool (@staff_member_required) - missed when this list was first
        # written, since travel had no user-facing pages yet at that
        # point. Same reasoning as every other disallowed path here: an
        # unauthenticated crawler just finds a login redirect.
        "Disallow: /travel/",
        # The staff-only internal analytics dashboard.
        "Disallow: /analytics/",
        "",
        f"Sitemap: https://{settings.SITE_DOMAIN}{reverse('core:sitemap')}",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


def sitemap_xml(request):
    """A hand-written sitemap rather than django.contrib.sitemaps - with
    only two genuinely public pages right now, the framework's extra
    moving parts (django.contrib.sites, per-model Sitemap classes) aren't
    worth it, and its default URL generation reads the domain off the
    incoming request/Site object - exactly the duplicate-hostname problem
    SITE_DOMAIN exists to avoid. Revisit once the app has real
    per-destination pages worth listing individually."""
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
