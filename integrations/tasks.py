import logging
import time

from celery import shared_task

from .climate import ClimateProviderError, get_climate_provider

logger = logging.getLogger(__name__)

# 2026-09-02: a first real dispatch of this task, with no delay between
# calls, made ~30 rapid-fire requests to Open-Meteo's free, keyless API
# and then hung completely - Celery's own `inspect active` still showed it
# "running" 12+ minutes later, while a brand-new, isolated request from the
# same container to the same endpoint succeeded in ~0.2s. The likely
# explanation: something in that burst tripped Open-Meteo's own abuse
# protection, and whatever it does to a since-blocked client (silently
# dropping the connection, or a DNS-level response) fell outside what
# `requests`' own `timeout=` parameter can bound - DNS resolution in
# particular has no timeout of its own in the requests/urllib3 stack, so a
# resolver-level hang can outlast a "5 second" HTTP timeout indefinitely.
# REQUEST_DELAY_SECONDS makes this task a considerate, slow citizen of a
# free public API instead of a burst client, which should avoid tripping
# whatever this was in the first place; CELERY_TASK_TIME_LIMIT below is the
# real safety net regardless of root cause - it guarantees this task can
# never occupy a worker slot indefinitely again, whatever the underlying
# cause turns out to be.
REQUEST_DELAY_SECONDS = 0.5
# Hard kill after 90 minutes. Measured directly (2026-09-02, a real 60-call
# slice with this exact delay): ~0.73s/call including the delay, so a full,
# genuinely-cold first run (4,608 destination/month combinations, e.g. a
# fresh production deploy with an empty cache) is realistically ~56
# minutes - 90 minutes leaves real margin above that while still bounding
# a hang of any cause, rather than letting it persist forever the way the
# undelayed first run just did. Every run after the first is far faster
# in practice, since get_monthly_climate() only makes a real HTTP call for
# entries that aren't already cached. This is a task-specific Celery
# `time_limit` (passed to the decorator below), not a Django/global
# CELERY_TASK_TIME_LIMIT setting - deliberately scoped to this one task
# rather than every task in the app. Celery enforces it itself (kills the
# child process handling the task once exceeded), no in-task handling
# needed; a killed run leaves whatever it already warmed safely cached -
# nothing to clean up, and the next scheduled run naturally continues from
# there. Accepted tradeoff: on the free plan's 2-worker-process capacity,
# a long first run occupies one of only two slots for its duration -
# acceptable since the app's other task (feedback learning) is lightweight
# and this only bites on the rare cold-start case, never on a routine
# re-run.
TASK_TIME_LIMIT_SECONDS = 60 * 90


@shared_task(time_limit=TASK_TIME_LIMIT_SECONDS)
def warm_climate_cache() -> dict:
    """Proactively populate the climate cache for every destination and
    month (2026-09-02, direct user request - "pode fazer o pre-warming do
    cache"), so a real recommendation request never has to make dozens or
    hundreds of cold, synchronous HTTP calls to the climate provider
    itself. Root cause of a real reported production timeout ("quero neve
    fim do ano" - a broad trip_type request whose month, December, hadn't
    been queried by anything yet): even after recommendations.scoring's
    same-day fix to filter by trip_type/cost before any climate lookup,
    a large category (100+ destinations) on a genuinely cold month can
    still take tens of seconds. Run on a schedule (see
    settings.CELERY_BEAT_SCHEDULE) well inside the climate provider's own
    7-day cache TTL, so real user requests should always find a warm
    cache in normal operation.

    Naturally idempotent and cheap to re-run: get_monthly_climate() checks
    its own cache first and only makes a real HTTP call for whatever isn't
    already warm, so a scheduled re-run mostly does nothing except for
    entries that have actually expired or are new (e.g. after a catalog
    expansion). Deliberately warms every month, not just the current one
    or a rolling near-term window - a traveler can reasonably ask about
    any month at any time (the reported bug was exactly that: "fim do
    ano" asked in September), and this task has no user-facing time
    budget the way a web request does, so there is no reason to leave any
    month deliberately cold.
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
