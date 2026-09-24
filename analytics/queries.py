"""Small, DB-aggregated query functions over the warehouse layer - no
dashboard framework, no in-Python aggregation. Supports the accommodation
search feature's own reporting needs (top-clicked destinations,
click-through rate, performance by a real traveler-preference dimension);
see documentation/16_ANALYTICS_ARCHITECTURE.md for the click-through-rate
and profile-dimension metric definitions these implement.

Never imported by recommendations.scoring or anything upstream of it -
this data describes affiliate-link engagement after a recommendation was
already made, and must never feed back into ranking. See that module's own
note on this.
"""

from datetime import date

from django.db.models import Count, Q

from .models import Event
from .warehouse.models import FactAcquisitionFunnel, FactRecommendation


def top_clicked_destinations(*, start_date: date, end_date: date, limit: int = 10):
    """Destinations ranked by accommodation-search-link clicks in the
    given date range, using fact_recommendations' existing session
    correlation - no separate click-count table to maintain."""
    return (
        FactRecommendation.objects.filter(
            recommended_at__date__gte=start_date, recommended_at__date__lte=end_date
        )
        .values("destination_slug")
        .annotate(clicks=Count("id", filter=Q(was_accommodation_clicked=True)))
        .filter(clicks__gt=0)
        .order_by("-clicks")[:limit]
    )


def accommodation_click_through_rate_by_destination(
    *, start_date: date, end_date: date, min_impressions: int = 1
):
    """CTR = clicks / eligible-recommendation-exposures, per destination.
    "Impression" here means a row in fact_recommendations - the
    destination was actually recommended in that conversation episode, not
    just that it exists in the catalog. min_impressions filters out
    destinations with too little exposure to draw a meaningful rate from."""
    return (
        FactRecommendation.objects.filter(
            recommended_at__date__gte=start_date, recommended_at__date__lte=end_date
        )
        .values("destination_slug")
        .annotate(
            impressions=Count("id"),
            clicks=Count("id", filter=Q(was_accommodation_clicked=True)),
        )
        .filter(impressions__gte=min_impressions)
        .order_by("-clicks")
    )


def acquisition_funnel(*, start_date: date, end_date: date, touch_type: str = "first"):
    """Acquisition performance by source/medium/campaign/content - the raw
    counts behind planning-start rate, recommendation rate, and
    accommodation-intent rate (divide these yourself with whatever
    denominator the question actually calls for - e.g. planning_starts /
    sessions). touch_type="first" (the default) answers "which channel
    originally brought these visitors here"; "latest" answers "which
    channel most recently reminded them to come back" - see
    fact_acquisition_funnel's own grain note for why almost every episode
    only ever has a "first" row.

    Deliberately "accommodation_clicks", never "conversions" or
    "bookings" - reached_accommodation_click only means the traveler
    clicked outbound to Booking.com, never that a booking happened."""
    return (
        FactAcquisitionFunnel.objects.filter(
            touch_type=touch_type,
            touched_at__date__gte=start_date,
            touched_at__date__lte=end_date,
        )
        .values("source", "medium", "campaign", "content")
        .annotate(
            sessions=Count("id"),
            planning_starts=Count("id", filter=Q(reached_planning=True)),
            recommendations=Count("id", filter=Q(reached_recommendation=True)),
            accommodation_clicks=Count("id", filter=Q(reached_accommodation_click=True)),
        )
        .order_by("-sessions")
    )


def acquisition_by_traveler_preference(
    *,
    start_date: date,
    end_date: date,
    trip_type: str | None = None,
    cost_of_living: int | None = None,
    limit: int = 10,
):
    """Accommodation-click acquisition breakdown segmented by a real
    traveler-preference dimension already captured on the click event's
    own frozen snapshot - never a live TravelerProfile join, never an
    inferred demographic trait. Answers "which channel/campaign/content
    attracts travelers with this preference" (e.g. cost_of_living=2 for
    "which source attracts budget travelers", trip_type="beach" for
    "which content attracts beach travelers"). Pass either or both."""
    if trip_type is None and cost_of_living is None:
        raise ValueError("Pass trip_type and/or cost_of_living.")

    events = Event.objects.filter(
        event_type="accommodation_outbound_click",
        created_at__date__gte=start_date,
        created_at__date__lte=end_date,
    )
    if trip_type is not None:
        events = events.filter(metadata__traveler_preferred_trip_types__contains=[trip_type])
    if cost_of_living is not None:
        events = events.filter(metadata__traveler_preferred_cost_of_living=cost_of_living)

    return (
        events.values(
            "metadata__acquisition__first_touch__source",
            "metadata__acquisition__first_touch__campaign",
            "metadata__acquisition__first_touch__content",
        )
        .annotate(clicks=Count("id"))
        .order_by("-clicks")[:limit]
    )


def top_destinations_by_traveler_trip_type(
    *, trip_type: str, start_date: date, end_date: date, limit: int = 10
):
    """Which destinations get the most accommodation clicks from
    travelers whose own TravelerProfile.preferred_trip_types includes
    `trip_type`? Segments on the click event's own profile-dimension
    snapshot (metadata.traveler_preferred_trip_types, captured at click
    time), not a live join against TravelerProfile - a traveler's
    preferences can change after the fact, and this is meant to describe
    what happened historically, not their current profile. Anonymous
    clicks (no snapshot) are naturally excluded, same as any other
    profile-segmented query."""
    return (
        Event.objects.filter(
            event_type="accommodation_outbound_click",
            created_at__date__gte=start_date,
            created_at__date__lte=end_date,
            metadata__traveler_preferred_trip_types__contains=[trip_type],
        )
        .values("metadata__destination_slug")
        .annotate(clicks=Count("id"))
        .order_by("-clicks")[:limit]
    )
