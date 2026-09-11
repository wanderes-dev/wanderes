from django.contrib.admin.views.decorators import staff_member_required
from django.db import connection
from django.shortcuts import render
from django.utils import timezone

from .models import DailyProductMetrics

# Staff-only internal dashboard - same staff_member_required +
# not-linked-from-nav pattern as travel.views's country admin tools, no
# new access-control concept here. Plain server-rendered tables on
# purpose, no JS charting library: correct data and metric definitions
# matter more than the dashboard being a project of its own.
LOOKBACK_DAYS = 30


@staff_member_required
def dashboard(request):
    daily_metrics = DailyProductMetrics.objects.order_by("-date")[:LOOKBACK_DAYS]

    destination_performance = _query(
        """
        SELECT
            d.name,
            d.country,
            COUNT(*) AS times_recommended,
            COUNT(*) FILTER (WHERE r.was_selected) AS times_selected,
            COUNT(*) FILTER (WHERE r.was_saved) AS times_saved
        FROM fact_recommendations r
        JOIN dim_destinations d ON d.slug = r.destination_slug
        WHERE r.recommended_at >= %(since)s
        GROUP BY d.name, d.country
        ORDER BY times_recommended DESC
        LIMIT 20
        """,
        since=timezone.now() - timezone.timedelta(days=LOOKBACK_DAYS),
    )

    locale_breakdown = _query(
        """
        SELECT COALESCE(NULLIF(locale, ''), '(unknown)') AS locale, COUNT(*) AS conversations
        FROM fact_conversations
        WHERE started_at >= %(since)s
        GROUP BY 1
        ORDER BY conversations DESC
        """,
        since=timezone.now() - timezone.timedelta(days=LOOKBACK_DAYS),
    )

    ai_operations = _query(
        """
        SELECT
            operation,
            event_type,
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE NOT success) AS failed,
            -- percentile_cont() returns double precision, not numeric -
            -- ROUND(double precision, integer) has no overload in
            -- Postgres, so the result must be cast to numeric first.
            ROUND((percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms))::numeric, 1) AS p50_ms,
            ROUND((percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms))::numeric, 1) AS p95_ms,
            ROUND((percentile_cont(0.99) WITHIN GROUP (ORDER BY latency_ms))::numeric, 1) AS p99_ms
        FROM fact_ai_requests
        WHERE created_at >= %(since)s
        GROUP BY operation, event_type
        ORDER BY total DESC
        """,
        since=timezone.now() - timezone.timedelta(days=LOOKBACK_DAYS),
    )

    latest = daily_metrics[0] if daily_metrics else None
    freshness_stale = bool(
        latest and (timezone.now() - latest.computed_at) > timezone.timedelta(hours=26)
    )

    return render(
        request,
        "analytics/dashboard.html",
        {
            "daily_metrics": daily_metrics,
            "destination_performance": destination_performance,
            "locale_breakdown": locale_breakdown,
            "ai_operations": ai_operations,
            "latest": latest,
            "freshness_stale": freshness_stale,
            "lookback_days": LOOKBACK_DAYS,
        },
    )


def _query(sql: str, **params) -> list[dict]:
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
