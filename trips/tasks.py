import logging

from celery import shared_task

logger = logging.getLogger(__name__)

# Not every piece of feedback should permanently change a preference -
# require a consistent pattern, not a single data point.
POSITIVE_RATING_THRESHOLD = 8
MIN_SIGNAL_COUNT = 2


@shared_task
def update_traveler_preferences_from_feedback(user_id: int) -> None:
    """Recompute a user's learned traveler preferences from all their feedback.

    Triggered by trips.signals on every Feedback save. Recomputes from scratch
    each run instead of incrementing stored counters - that's what makes it
    retry-safe: running it twice for the same feedback (or out of order)
    gives the same result, never a double-counted one.

    Guards against silently rewriting a user's preferences:
    - preferred_trip_types is additive only, never removes a type the user
      set manually or a previous run added. (If they manually remove a type
      but keep rating that kind of destination highly, a later run can add
      it back - a known edge case, not a bug.)
    - preferred_cost_of_living only gets set automatically if the user
      hasn't already set it themselves - an explicit choice always wins.
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
