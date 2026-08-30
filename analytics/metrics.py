"""Core Product Analytics metrics (Phase 17, 15_IMPLEMENTATION_GUIDE.md §21).

premium_conversion and affiliate_clicks from the guide's "Core Metrics" list
are deliberately NOT implemented here, matching the Phase 17 decision to
defer premium_started/affiliate_link_clicked entirely - there is no
monetization or affiliate feature yet to measure.

"Active user" (per the guide's own warning - "should mean a user performing
a meaningful action, not simply opening the website" - and the Phase 17
decision): an authenticated user who submitted at least one message to the
chat (a `travel_question_submitted` event) within the window. Anonymous chat
use is tracked (see analytics.services) but never counts toward these
user-based metrics, since there is no stable identity to count against.
"""

from datetime import datetime, time, timedelta

from django.utils import timezone

from .models import Event


def _active_user_ids_between(start, end) -> set[int]:
    return set(
        Event.objects.filter(
            event_type="travel_question_submitted",
            user__isnull=False,
            created_at__gte=start,
            created_at__lt=end,
        )
        .values_list("user_id", flat=True)
        .distinct()
    )


def active_user_ids(window_days: int, *, as_of=None) -> set[int]:
    as_of = as_of or timezone.now()
    start = as_of - timedelta(days=window_days)
    return _active_user_ids_between(start, as_of)


def dau(*, as_of=None) -> int:
    return len(active_user_ids(1, as_of=as_of))


def wau(*, as_of=None) -> int:
    return len(active_user_ids(7, as_of=as_of))


def mau(*, as_of=None) -> int:
    return len(active_user_ids(30, as_of=as_of))


def _rate_per_active_user(event_type: str, window_days: int, as_of) -> float | None:
    as_of = as_of or timezone.now()
    start = as_of - timedelta(days=window_days)
    active = active_user_ids(window_days, as_of=as_of)
    if not active:
        return None
    count = Event.objects.filter(
        event_type=event_type, user_id__in=active, created_at__gte=start, created_at__lt=as_of
    ).count()
    return count / len(active)


def recommendations_per_active_user(*, window_days: int = 30, as_of=None) -> float | None:
    return _rate_per_active_user("recommendation_generated", window_days, as_of)


def trips_per_active_user(*, window_days: int = 30, as_of=None) -> float | None:
    return _rate_per_active_user("trip_created", window_days, as_of)


def feedback_rate(*, window_days: int = 30, as_of=None) -> float | None:
    """feedback_submitted events per active user - a proxy for how often
    active users close the loop with feedback, not a percentage of requests."""
    return _rate_per_active_user("feedback_submitted", window_days, as_of)


def retention_rate(reference_date, *, window_days: int = 7) -> float | None:
    """Fraction of users active on `reference_date` who were also active
    again at least once in the following `window_days` days. Returns None
    if nobody was active on `reference_date` (rate would be undefined)."""
    day_start = timezone.make_aware(datetime.combine(reference_date, time.min))
    day_end = day_start + timedelta(days=1)
    cohort = _active_user_ids_between(day_start, day_end)
    if not cohort:
        return None

    returning_start = day_end
    returning_end = day_end + timedelta(days=window_days)
    returning = _active_user_ids_between(returning_start, returning_end)

    return len(cohort & returning) / len(cohort)
