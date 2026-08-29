import logging

from celery import shared_task

logger = logging.getLogger(__name__)

# Phase 15 ("Learning From Feedback") thresholds, decided with the user
# 2026-08-29: not every piece of feedback should permanently change a
# preference - require a consistent pattern, not a single data point.
POSITIVE_RATING_THRESHOLD = 8
MIN_SIGNAL_COUNT = 2


@shared_task
def update_traveler_preferences_from_feedback(user_id: int) -> None:
    """Recompute a user's learned traveler preferences from all their feedback.

    Triggered by trips.signals on every Feedback save. Recomputes from
    scratch each run (rather than incrementing stored counters), which is
    what makes this retry-safe and duplicate-processing-safe per Phase
    15's review criteria - running it twice for the same feedback (or out
    of order) produces the same result, not a double-counted one.

    Controls against the AI "silently rewriting important user
    preferences" (also a Phase 15 review criterion):
    - preferred_trip_types is additive only - never removes a type the
      user set manually or that a previous run added. (Accepted edge case,
      confirmed with the user: if they manually remove a trip type but
      keep rating that type of destination highly, a later run can add it
      back - not tracked as a deliberate removal.)
    - preferred_cost_of_living is only ever set automatically if the user
      has not already set it themselves - an explicit choice always wins
      over an inferred one.
    """
    from trips.models import Feedback
    from users.models import TravelerProfile

    feedback_entries = list(
        Feedback.objects.filter(user_id=user_id, destination__isnull=False).select_related(
            "destination"
        )
    )
    if not feedback_entries:
        return

    profile, _ = TravelerProfile.objects.get_or_create(user_id=user_id)

    trip_type_ratings: dict[str, list[int]] = {}
    cost_tier_ratings: dict[int, list[int]] = {}
    for feedback in feedback_entries:
        trip_type_ratings.setdefault(feedback.destination.trip_type, []).append(feedback.rating)
        cost_tier_ratings.setdefault(feedback.destination.cost_of_living, []).append(
            feedback.rating
        )

    updated_trip_types = set(profile.preferred_trip_types)
    for trip_type, ratings in trip_type_ratings.items():
        if trip_type in updated_trip_types:
            continue
        if len(ratings) >= MIN_SIGNAL_COUNT and _average(ratings) >= POSITIVE_RATING_THRESHOLD:
            logger.info(
                "Learning: adding preferred_trip_types=%r for user_id=%s "
                "(%d ratings, avg %.1f)",
                trip_type,
                user_id,
                len(ratings),
                _average(ratings),
            )
            updated_trip_types.add(trip_type)
    profile.preferred_trip_types = sorted(updated_trip_types)

    if profile.preferred_cost_of_living is None:
        best_cost_tier = None
        best_avg = 0.0
        for cost_tier, ratings in cost_tier_ratings.items():
            if len(ratings) < MIN_SIGNAL_COUNT:
                continue
            avg = _average(ratings)
            if avg >= POSITIVE_RATING_THRESHOLD and avg > best_avg:
                best_avg = avg
                best_cost_tier = cost_tier
        if best_cost_tier is not None:
            logger.info(
                "Learning: setting preferred_cost_of_living=%s for user_id=%s (avg rating %.1f)",
                best_cost_tier,
                user_id,
                best_avg,
            )
            profile.preferred_cost_of_living = best_cost_tier

    profile.save()


def _average(values: list[int]) -> float:
    return sum(values) / len(values)
