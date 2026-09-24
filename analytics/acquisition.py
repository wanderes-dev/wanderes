"""First-party acquisition attribution - which marketing channel actually
brought a visitor to Wanderes, and did it lead to real travel intent.

Deliberately not a middleware: capture_acquisition() is called explicitly
from the app's actual landing surfaces (core.views.landing, ai.views.chat_page)
rather than on every request, so it never runs for API calls, health checks,
or static assets - matches "do not generate an analytics event on every
ordinary page request."

Two touches are tracked in the visitor's existing Django session (the same
DB-backed session ai.memory already keys anonymous conversations by - no
new identity mechanism):
- first_touch: captured once, the first time this session is ever seen,
  and never overwritten afterward - whatever channel genuinely brought
  this visitor to Wanderes the first time.
- latest_touch: starts equal to first_touch, and only updates when a
  request arrives carrying a genuinely new set of UTM parameters (a real
  campaign-link click, not a page refresh or plain internal navigation).

A compact snapshot of both is attached to the funnel events that matter
(acquisition_captured itself, travel_question_submitted,
recommendation_generated, accommodation_outbound_click) at the moment
they're recorded - not just left as a live pointer into the mutable
session - so a downstream event's meaning can never change retroactively
if the same visitor's session state changes later (e.g. a second,
different-channel visit updates latest_touch after the fact)."""

import re
from urllib.parse import urlparse

from .services import record_event

UTM_PARAMS = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term")
_UTM_MAX_LENGTH = 100
# Strips everything outside a conservative allowlist rather than trying to
# detect specific attack patterns - removes HTML/script metacharacters
# (<, >, ", ', ;, backslash, /) by construction. Real campaign
# identifiers (the spec's own examples: "warm_november", "creative_01",
# "organic_social") never need anything outside this set.
_UTM_DISALLOWED_CHARS = re.compile(r"[^A-Za-z0-9 _\-.+]")

_SEARCH_ENGINE_HOSTS = {
    "google": ("google.",),
    "bing": ("bing.com",),
    "duckduckgo": ("duckduckgo.com",),
    "yahoo": ("yahoo.com",),
}
_SOCIAL_HOSTS = {
    "instagram": ("instagram.com",),
    "tiktok": ("tiktok.com",),
}


def _clean_utm_value(raw: str | None) -> str | None:
    if not raw:
        return None
    cleaned = _UTM_DISALLOWED_CHARS.sub("", raw).strip()
    return cleaned[:_UTM_MAX_LENGTH] or None


def _extract_utms(request) -> dict | None:
    """Reads utm_* query params, sanitized. Returns None (not a dict of
    nulls) when none are present at all - a request with zero UTM
    parameters is not "an explicit touch with empty fields", it's simply
    not carrying campaign attribution."""
    values = {param[4:]: _clean_utm_value(request.GET.get(param)) for param in UTM_PARAMS}
    if not any(values.values()):
        return None
    return values


def _classify_referrer(referrer: str | None) -> tuple[str | None, str]:
    """Small, deterministic (source, medium) inference from the HTTP
    Referer header - only used as a fallback when no UTMs are present.
    Never stores the full referrer URL, just a coarse classification (and,
    for an unrecognized referring site, its bare hostname - not the full
    path/query, which could carry a search query or other detail worth
    not retaining)."""
    if not referrer:
        return None, "direct"
    try:
        host = urlparse(referrer).netloc.lower()
    except ValueError:
        return None, "direct"
    if not host:
        return None, "direct"
    bare_host = host[4:] if host.startswith("www.") else host

    for source, needles in _SEARCH_ENGINE_HOSTS.items():
        if any(needle in bare_host for needle in needles):
            return source, "organic_search"
    for source, needles in _SOCIAL_HOSTS.items():
        if any(needle in bare_host for needle in needles):
            return source, "organic_social"
    return bare_host[:_UTM_MAX_LENGTH], "referral"


def _conversation_key(request) -> str:
    """Mirrors ai.memory.conversation_key() exactly, deliberately
    duplicated rather than imported - analytics is a shared/foundational
    app several others (ai, integrations.climate) already depend on;
    importing from ai here would create the reverse dependency instead.
    Keep in sync if that function's logic ever changes."""
    user = request.user if getattr(request.user, "is_authenticated", False) else None
    if user is not None:
        return f"chat-history:user:{user.pk}"
    return f"chat-history:session:{request.session.session_key}"


def _record_touch(request, touch: dict, *, touch_type: str) -> None:
    if not request.session.session_key:
        request.session.save()
    record_event(
        "acquisition_captured",
        user=request.user if request.user.is_authenticated else None,
        request=request,
        metadata={"touch_type": touch_type, **touch},
        conversation_key=_conversation_key(request),
        locale=request.LANGUAGE_CODE,
    )


def capture_acquisition(request) -> None:
    """Call once, near the top of a real landing-surface view (currently
    core.views.landing and ai.views.chat_page). Idempotent per distinct
    touch - a page refresh or plain internal navigation is always a
    no-op: no session write, no event, first_touch is never disturbed."""
    utms = _extract_utms(request)
    acquisition = request.session.get("acquisition")

    if acquisition is None:
        if utms:
            touch = utms
        else:
            source, medium = _classify_referrer(request.META.get("HTTP_REFERER"))
            touch = {
                "source": source,
                "medium": medium,
                "campaign": None,
                "content": None,
                "term": None,
            }
        request.session["acquisition"] = {"first_touch": touch, "latest_touch": touch}
        _record_touch(request, touch, touch_type="first")
        return

    if utms and utms != acquisition.get("latest_touch"):
        request.session["acquisition"] = {
            "first_touch": acquisition["first_touch"],
            "latest_touch": utms,
        }
        _record_touch(request, utms, touch_type="latest")


def get_acquisition_snapshot(request) -> dict | None:
    """A compact {"first_touch": {...}, "latest_touch": {...}} snapshot
    for attaching to a funnel event's own metadata - None when this
    session never went through capture_acquisition() at all (e.g. a
    direct API call in a test, or a session that predates this feature)."""
    acquisition = request.session.get("acquisition")
    if not acquisition:
        return None
    return {"first_touch": acquisition["first_touch"], "latest_touch": acquisition["latest_touch"]}
