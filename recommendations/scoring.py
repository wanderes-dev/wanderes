from dataclasses import dataclass

from integrations.climate import ClimateProviderError, get_climate_provider
from travel.models import Destination
from trips.models import Trip
from users.models import TravelerProfile

# Tunable weights for the v1 scoring formula (05_AI_DESIGN.md §6). Kept as
# simple constants rather than a config system - "should remain simple
# initially and evolve based on real usage."
PREFERENCE_FIT_BONUS = 2.0
REPETITION_PENALTY = 3.0
BUDGET_FIT_WEIGHT = 0.5
TEMPERATURE_FIT_WEIGHT = 0.1
TEMPERATURE_FIT_CAP_C = 10.0


@dataclass(frozen=True)
class RecommendationRequest:
    """Deterministic, already-extracted constraints for one recommendation request.

    Turning a natural-language request ("somewhere warm in October") into
    these numeric fields is Intent & Constraint Extraction - the future AI
    orchestration layer's job (Phase 9), not this module's. This module
    only handles what happens once the constraints are already explicit.
    """

    month: int
    min_temp_c: float | None = None
    max_temp_c: float | None = None
    max_cost_of_living: int | None = None
    excluded_slugs: frozenset = frozenset()
    user: object | None = None  # users.models.User or AnonymousUser; None for a bare request


@dataclass(frozen=True)
class ScoredDestination:
    """A candidate destination that survived hard constraints, with its score
    broken into the individual factors that produced it - so a future AI
    explanation layer can describe *why*, rather than re-deriving it."""

    destination: Destination
    avg_high_c: float
    avg_low_c: float
    preference_fit: float
    budget_fit: float
    temperature_fit: float
    repetition_penalty: float
    score: float


def generate_recommendations(
    request: RecommendationRequest, *, climate_provider=None
) -> list[ScoredDestination]:
    """Filter candidate destinations by hard constraints, then score and rank the rest.

    Pipeline (05_AI_DESIGN.md §2, 14_MVP_IMPLEMENTATION_PLAN.md Milestone 5
    "Recommendation Logic"): Candidate Destination -> Hard Constraints ->
    Basic Score -> Ranking. AI Explanation is a later step this function
    does not perform.
    """
    climate_provider = climate_provider or get_climate_provider()

    candidates = Destination.objects.exclude(slug__in=request.excluded_slugs)
    preferred_trip_types = _preferred_trip_types(request.user)
    visited_slugs = _visited_destination_slugs(request.user)

    scored = []
    for destination in candidates:
        try:
            climate = climate_provider.get_monthly_climate(
                latitude=float(destination.latitude),
                longitude=float(destination.longitude),
                month=request.month,
            )
        except ClimateProviderError:
            # Graceful degradation (10_EXTERNAL_INTEGRATIONS.md §5): skip a
            # destination we can't get climate data for instead of failing
            # the whole request.
            continue

        if request.min_temp_c is not None and climate.avg_high_c < request.min_temp_c:
            continue
        if request.max_temp_c is not None and climate.avg_high_c > request.max_temp_c:
            continue
        if (
            request.max_cost_of_living is not None
            and destination.cost_of_living > request.max_cost_of_living
        ):
            continue

        preference_fit = (
            PREFERENCE_FIT_BONUS if destination.trip_type in preferred_trip_types else 0.0
        )

        budget_fit = 0.0
        if request.max_cost_of_living is not None:
            cost_headroom = request.max_cost_of_living - destination.cost_of_living
            budget_fit = cost_headroom * BUDGET_FIT_WEIGHT

        temperature_fit = 0.0
        if request.min_temp_c is not None:
            margin = min(climate.avg_high_c - request.min_temp_c, TEMPERATURE_FIT_CAP_C)
            temperature_fit = margin * TEMPERATURE_FIT_WEIGHT

        repetition_penalty = REPETITION_PENALTY if destination.slug in visited_slugs else 0.0

        score = preference_fit + budget_fit + temperature_fit - repetition_penalty

        scored.append(
            ScoredDestination(
                destination=destination,
                avg_high_c=climate.avg_high_c,
                avg_low_c=climate.avg_low_c,
                preference_fit=preference_fit,
                budget_fit=budget_fit,
                temperature_fit=temperature_fit,
                repetition_penalty=repetition_penalty,
                score=score,
            )
        )

    scored.sort(key=lambda item: item.score, reverse=True)
    return scored


def _preferred_trip_types(user) -> frozenset:
    if user is None or not user.is_authenticated:
        return frozenset()
    profile = TravelerProfile.objects.filter(user=user).first()
    return frozenset(profile.preferred_trip_types) if profile else frozenset()


def _visited_destination_slugs(user) -> frozenset:
    # Previously-visited destinations should generally rank lower
    # (05_AI_DESIGN.md §5), not be excluded outright - so this is a soft
    # scoring penalty, not a hard constraint.
    if user is None or not user.is_authenticated:
        return frozenset()
    return frozenset(
        Trip.objects.filter(user=user, status="completed").values_list(
            "destination__slug", flat=True
        )
    )
