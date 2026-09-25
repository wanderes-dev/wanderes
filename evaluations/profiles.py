"""Throwaway synthetic User/TravelerProfile/Trip/TravelHistoryEntry rows
for scenarios that need to simulate an authenticated traveler -
preference_fit and repetition_penalty in recommendations.scoring only
ever apply to a real authenticated user
(_preferred_trip_types/_visited_destination_slugs both return an empty
set for anonymous requests), so a scenario testing either one needs a
real row in the database, not just a dict.

Always created and torn down within one scenario run - never left
behind in whatever database `evaluate_recommendations` is pointed at.
Tagged with an @example.invalid address (RFC 2606 reserved, guaranteed
never a real deliverable domain) plus the scenario id, so a crashed
run's leftovers - if the `finally` block itself never got to run - are
trivially identifiable and safe to clean up by hand.
"""

from __future__ import annotations

from contextlib import contextmanager

from travel.models import Destination
from trips.models import TravelHistoryEntry, Trip
from users.models import TravelerProfile, User

_PROFILE_FIELDS = frozenset(
    {
        "preferred_trip_types",
        "preferred_cost_of_living",
        "home_country",
        "travelers_count",
        "budget_amount",
        "budget_period",
        "budget_currency",
    }
)


@contextmanager
def synthetic_traveler(scenario_id: str, profile_overrides: dict | None):
    """Yields None (anonymous) when the scenario declares no profile at
    all - the common case. Only creates real rows when profile_overrides
    is actually set."""
    if not profile_overrides:
        yield None
        return

    email = f"eval-synthetic-{scenario_id.lower()}@example.invalid"
    user = User.objects.create_user(email=email, password=None)
    try:
        profile_fields = {k: v for k, v in profile_overrides.items() if k in _PROFILE_FIELDS}
        if profile_fields:
            TravelerProfile.objects.update_or_create(user=user, defaults=profile_fields)

        for slug in profile_overrides.get("completed_trip_slugs") or ():
            destination = Destination.objects.filter(slug=slug).first()
            if destination is not None:
                Trip.objects.create(user=user, destination=destination, status="completed")

        for slug in profile_overrides.get("travel_history_slugs") or ():
            destination = Destination.objects.filter(slug=slug).first()
            if destination is not None:
                TravelHistoryEntry.objects.create(user=user, destination=destination)

        yield user
    finally:
        user.delete()  # cascades to TravelerProfile/Trip/TravelHistoryEntry
