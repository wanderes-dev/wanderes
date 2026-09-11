import logging
from datetime import timedelta
from pathlib import Path

from celery import shared_task
from django.db import connection
from django.utils import timezone

logger = logging.getLogger(__name__)

SQL_PATH = Path(__file__).resolve().parent / "warehouse" / "sql" / "daily_product_metrics.sql"


@shared_task(autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def refresh_daily_metrics(target_date=None) -> None:
    """Recompute analytics.models.DailyProductMetrics for one calendar date,
    full recompute-and-upsert - same idempotent/retry-safe-by-recomputing
    pattern as trips.tasks.update_traveler_preferences_from_feedback.
    Unlike that task, this one configures Celery retry (autoretry_for/
    retry_backoff): it's a scheduled batch job rather than a per-request
    write like record_event, so a transient DB blip should retry instead
    of silently skipping a whole day - and recomputing from scratch means
    a retry can never double-count.

    `target_date=None` (the real scheduled-run case, see
    settings.CELERY_BEAT_SCHEDULE) computes yesterday (UTC), never today,
    to avoid racing events still arriving for the current day. Pass an
    explicit date for manual backfills/tests.
    """
    if target_date is None:
        target_date = timezone.now().date() - timedelta(days=1)

    sql = SQL_PATH.read_text(encoding="utf-8")
    with connection.cursor() as cursor:
        cursor.execute(sql, {"date": target_date})
        columns = [col[0] for col in cursor.description]
        row = dict(zip(columns, cursor.fetchone(), strict=True))

    from .models import DailyProductMetrics

    DailyProductMetrics.objects.update_or_create(date=target_date, defaults=row)
    logger.info("Refreshed daily product metrics for %s.", target_date)
