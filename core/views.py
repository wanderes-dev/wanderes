import logging

from django.db import connections
from django.db.utils import OperationalError
from django.http import JsonResponse
from django.shortcuts import render

from travel.models import Destination

logger = logging.getLogger(__name__)


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
