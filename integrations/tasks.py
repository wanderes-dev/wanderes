import logging
import time

from celery import shared_task

from .climate import ClimateProviderError, get_climate_provider

logger = logging.getLogger(__name__)

# The first real run of this task, with no delay between calls, fired ~30
# rapid requests at Open-Meteo's free API and then hung completely -
# `celery inspect active` still showed it "running" 12+ minutes later,
# while a fresh, isolated request to the same endpoint succeeded in
# ~0.2s. Best guess: the burst tripped Open-Meteo's abuse protection, and
# whatever it does to a blocked client falls outside what `timeout=` can
# bound - DNS resolution in particular has no timeout of its own in the
# requests/urllib3 stack, so a resolver-level hang can outlast a "5
# second" HTTP timeout indefinitely. This delay makes the task a slower,
# more considerate client instead of a burst; TASK_TIME_LIMIT_SECONDS
# below is the real safety net regardless of root cause.
REQUEST_DELAY_SECONDS = 0.5
# Hard kill after 90 minutes. A real 60-call slice at this delay measured
# ~0.73s/call including the sleep, so a genuinely cold first run (4,608
# destination/month combinations - e.g. a fresh prod deploy with an empty
# cache) is realistically ~56 minutes. 90 minutes leaves real margin
# above that while still bounding a hang of any cause. Every run after
# the first is much faster since get_monthly_climate() only hits the
# network for entries that aren't already cached.
#
# This is a task-specific Celery `time_limit` (see the decorator below),
# not the global CELERY_TASK_TIME_LIMIT setting - scoped to this one task
# on purpose. Celery kills the child process itself once it's exceeded,
# so there's nothing to clean up in-task - whatever got warmed before the
# kill stays cached, and the next scheduled run just picks up from there.
#
# Tradeoff: on the free plan's 2-worker capacity, a long first run ties
# up one of only two slots for its duration. Acceptable since the other
# task (feedback learning) is lightweight and this only bites on a rare
# cold start, not routine re-runs.
TASK_TIME_LIMIT_SECONDS = 60 * 90


@shared_task(time_limit=TASK_TIME_LIMIT_SECONDS)
def warm_climate_cache() -> dict:
    """Proactively warms the climate cache for every destination and
    month, so a real recommendation request never has to make dozens (or
    hundreds) of cold, synchronous HTTP calls to the climate provider.

    This exists because of a real production timeout: a broad request
    for a month nothing had queried yet (December, asked for in
    September) took too long even after scoring started filtering by
    trip_type/cost before any climate lookup - a large category (100+
    destinations) on a genuinely cold month can still take tens of
    seconds. Runs on a schedule (settings.CELERY_BEAT_SCHEDULE) well
    inside the climate provider's own 7-day cache TTL, so normal traffic
    should always hit a warm cache.

    Idempotent and cheap to re-run - get_monthly_climate() checks its own
    cache first, so a scheduled re-run mostly touches only what's expired
    or new. Warms every month, not just the current one or a near-term
    window: a traveler can ask about any month at any time, and this
    task has no user-facing time budget the way a web request does, so
    there's no reason to leave anything cold.
    """
    from travel.models import Destination

    climate_provider = get_climate_provider()
    warmed = 0
    failed = 0
    for destination in Destination.objects.all():
        for month in range(1, 13):
            try:
                climate_provider.get_monthly_climate(
                    latitude=float(destination.latitude),
                    longitude=float(destination.longitude),
                    month=month,
                )
                warmed += 1
            except ClimateProviderError:
                failed += 1
                logger.warning(
                    "Could not warm climate cache. destination=%s month=%s",
                    destination.slug,
                    month,
                )
            time.sleep(REQUEST_DELAY_SECONDS)

    logger.info("Climate cache warming complete. warmed=%s failed=%s", warmed, failed)
    return {"warmed": warmed, "failed": failed}
