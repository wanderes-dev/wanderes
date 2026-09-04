import logging
import time
from dataclasses import dataclass

from integrations.climate import ClimateProviderError, get_climate_provider
from travel.geography import countries_in_continent
from travel.models import Destination
from trips.models import TravelHistoryEntry, Trip
from users.models import TravelerProfile

logger = logging.getLogger(__name__)

# Tunable weights for the v1 scoring formula (05_AI_DESIGN.md §6). Kept as
# simple constants rather than a config system - "should remain simple
# initially and evolve based on real usage."
PREFERENCE_FIT_BONUS = 2.0
REPETITION_PENALTY = 3.0
BUDGET_FIT_WEIGHT = 0.5
TEMPERATURE_FIT_WEIGHT = 0.1
TEMPERATURE_FIT_CAP_C = 10.0

# 2026-09-04, real production timeout ("montar um eurotrip de 5 dias" -
# a request naming no trip_type/max_cost_of_living, so the 2026-09-02 fix
# below has nothing to filter on and the DB-level candidate set is the
# full ~384-destination catalog): the climate provider is only ever
# queried synchronously, one destination at a time, each call bounded at
# integrations.climate.open_meteo.REQUEST_TIMEOUT_SECONDS=5s. In normal
# operation integrations.tasks.warm_climate_cache keeps this cache warm
# well inside its 7-day TTL, so real requests rarely hit more than a
# handful of cold entries - but "rarely" isn't "never" (a newly-added
# destination, a just-expired entry, a transient warm-cache-task failure),
# and gunicorn's default --timeout is only 30s, shared with however long
# intent extraction/explanation generation already took. Enough cold
# entries in a row - which an unconstrained, catalog-wide request like
# this one makes far more likely - can still exceed that, and gunicorn
# then kills the *entire worker process* (a much worse failure than one
# missing destination). This budget bounds the worst case: once elapsed
# wall-clock time in the loop below crosses it, stop looking up more
# candidates and return whatever's already been scored, exactly the same
# "graceful degradation, never let one slow lookup take down the whole
# request" principle already applied to a single failed lookup
# (ClimateProviderError -> skip and continue) two paragraphs down -
# generalized from "this one lookup failed" to "we've spent our fair
# share of the request's time budget." Deliberately sequential, not
# parallelized - a real prior incident (see integrations/tasks.py's
# warm_climate_cache docstring) found a burst of concurrent requests to
# Open-Meteo's free API tripped its abuse protection in a way that
# escaped `requests`' own per-call timeout entirely (a DNS/connection-level
# hang, not a slow HTTP transfer) - trading a bounded, sequential partial
# result for a small chance of a much worse, unbounded hang was rejected.
CLIMATE_LOOKUP_TIME_BUDGET_SECONDS = 15.0


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
    trip_type: str | None = None  # one of travel.models.TRIP_TYPE_CHOICES, or None for any
    # One of travel.geography.CONTINENT_CHOICES, or None for any continent
    # (2026-09-04, real production bug: "Eurotrip" recommendation cards
    # included Bali/Marrakech/Chiang Mai alongside the genuinely European
    # options - nothing here could express "Europe" as a hard constraint
    # at all before this field existed).
    continent: str | None = None
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

    # trip_type/max_cost_of_living are applied as real DB-level filters
    # BEFORE any climate lookups (2026-09-02 fix - previously these were
    # checked in Python only after fetching climate for every remaining
    # candidate, meaning a specific request like "beach" still made a real
    # HTTP call to the climate provider for all ~380 non-beach destinations
    # first, only to discard them a moment later). Each uncached lookup is
    # a real synchronous HTTP call (up to REQUEST_TIMEOUT_SECONDS=5s) - at
    # the current 384-destination catalog size, doing this for the whole
    # catalog on every request was slow enough to cause real production
    # timeouts (reported live, 2026-09-02: "quero neve fim do ano" - a
    # trip_type=nature request - returned a generic error instead of an
    # answer). min_temp_c/max_temp_c can't be pushed down this way since
    # temperature isn't stored on Destination - it only exists once the
    # climate provider is actually called, so those two stay as
    # post-lookup checks below exactly as before.
    candidates = Destination.objects.exclude(slug__in=request.excluded_slugs)
    if request.trip_type is not None:
        candidates = candidates.filter(trip_type=request.trip_type)
    if request.max_cost_of_living is not None:
        candidates = candidates.filter(cost_of_living__lte=request.max_cost_of_living)
    if request.continent is not None:
        # Same DB-level-filter-before-any-climate-lookup treatment as
        # trip_type/max_cost_of_living above, for the same reason -
        # skipping this would mean "Europe" narrows nothing at all, and
        # every non-European destination gets a real climate lookup only
        # to be silently included anyway (2026-09-04 bug: a "Eurotrip"
        # request's cards included Bali, Marrakech, Chiang Mai).
        candidates = candidates.filter(country__in=countries_in_continent(request.continent))

    preferred_trip_types = _preferred_trip_types(request.user)
    visited_slugs = _visited_destination_slugs(request.user)

    scored = []
    loop_started_at = time.monotonic()
    for destination in candidates:
        if time.monotonic() - loop_started_at > CLIMATE_LOOKUP_TIME_BUDGET_SECONDS:
            logger.warning(
                "Climate lookup time budget (%ss) exceeded after scoring %s "
                "destination(s) - returning partial results rather than risking "
                "a request timeout. month=%s trip_type=%s",
                CLIMATE_LOOKUP_TIME_BUDGET_SECONDS,
                len(scored),
                request.month,
                request.trip_type,
            )
            break
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
    # (05_AI_DESIGN.md §5, 14_MVP_IMPLEMENTATION_PLAN.md Milestone 7), not
    # be excluded outright - so this is a soft scoring penalty, not a hard
    # constraint. Two independent sources count as "visited": a completed
    # Trip, or a manually-recorded TravelHistoryEntry (Phase 12) - a user
    # doesn't need a full Trip on file just to tell us they've been
    # somewhere before.
    if user is None or not user.is_authenticated:
        return frozenset()
    completed_trip_slugs = Trip.objects.filter(user=user, status="completed").values_list(
        "destination__slug", flat=True
    )
    history_slugs = TravelHistoryEntry.objects.filter(user=user).values_list(
        "destination__slug", flat=True
    )
    return frozenset(completed_trip_slugs) | frozenset(history_slugs)
