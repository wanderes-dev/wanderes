import ipaddress
import logging

from .models import EVENT_TYPE_CHOICES, Event

logger = logging.getLogger(__name__)

EVENT_TYPE_KEYS = {key for key, _label in EVENT_TYPE_CHOICES}

# Anonymization masks (Phase 17 decision, 2026-08-30): zero the last IPv4
# octet / keep only the IPv6 /48 prefix before ever storing an anonymous
# visitor's address - the same approach used by privacy-conscious analytics
# tools (e.g. Google Analytics', Matomo's IP anonymization). Reduces
# re-identification risk while still letting metrics distinguish separate
# anonymous visitors well enough to be useful.
IPV4_ANONYMIZATION_PREFIX = 24
IPV6_ANONYMIZATION_PREFIX = 48


def record_event(event_type: str, *, user=None, request=None, metadata=None) -> None:
    """Record one product-analytics event.

    Never raises: analytics is a non-critical side channel (Phase 16's own
    review criteria - don't let non-critical work affect the main
    request/response flow), so a failure here is logged and swallowed
    rather than breaking registration, chat, trip creation, or feedback.

    `user=None` records an anonymous event. `request` is only used in that
    case, to resolve and anonymize the visitor's IP (per the Phase 17
    decision to track anonymous chat interactions by IP rather than a
    session identifier) - it's ignored for authenticated events.
    """
    if event_type not in EVENT_TYPE_KEYS:
        logger.warning("Ignoring unknown analytics event_type=%r", event_type)
        return

    is_authenticated = user is not None and user.is_authenticated
    anonymized_ip = None
    if not is_authenticated:
        user = None
        anonymized_ip = _anonymize_ip(_client_ip(request)) if request is not None else None
        if anonymized_ip is None:
            logger.warning(
                "Could not resolve a client IP for anonymous event_type=%r - skipping.", event_type
            )
            return

    try:
        Event.objects.create(
            event_type=event_type,
            user=user,
            anonymized_ip=anonymized_ip,
            metadata=metadata or {},
        )
    except Exception:
        logger.warning("Failed to record analytics event_type=%r", event_type, exc_info=True)


def _client_ip(request) -> str | None:
    return request.META.get("REMOTE_ADDR")


def _anonymize_ip(raw_ip: str | None) -> str | None:
    if not raw_ip:
        return None
    try:
        address = ipaddress.ip_address(raw_ip)
    except ValueError:
        return None

    prefix = IPV4_ANONYMIZATION_PREFIX if address.version == 4 else IPV6_ANONYMIZATION_PREFIX
    network = ipaddress.ip_network(f"{address}/{prefix}", strict=False)
    return str(network.network_address)
