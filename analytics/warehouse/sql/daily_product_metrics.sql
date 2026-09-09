-- daily_product_metrics
--
-- Not a view - a parameterized query (%(date)s) run once per day by
-- analytics.tasks.refresh_daily_metrics to populate
-- analytics.models.DailyProductMetrics, the one genuinely materialized
-- table in this warehouse. Queries the fact_*/dim_* views and
-- analytics_event directly rather than being a view itself, since a
-- day-bounded aggregate needs a parameter a plain CREATE VIEW can't take.
--
-- Independent scalar subqueries, not one big JOIN with conditional
-- aggregation - each is planned separately, which is less "clever" SQL
-- but far easier to read, verify, and extend one metric at a time. Fine
-- at current and reasonably foreseeable data volumes; revisit only if
-- this query itself becomes the bottleneck (see
-- documentation/16_ANALYTICS_ARCHITECTURE.md's scaling section).
SELECT
    (SELECT COUNT(*) FROM fact_conversations
     WHERE started_at::date = %(date)s) AS conversations_started,
    (SELECT COUNT(*) FROM fact_conversations
     WHERE started_at::date = %(date)s AND user_id IS NULL) AS unique_anonymous_conversations,
    (SELECT COALESCE(SUM(message_count), 0) FROM fact_conversations
     WHERE started_at::date = %(date)s) AS messages_sent,
    (SELECT COUNT(*) FROM fact_conversations
     WHERE started_at::date = %(date)s AND reached_recommendation) AS conversations_reached_recommendation,
    (SELECT COUNT(*) FROM analytics_event
     WHERE event_type = 'recommendation_generated' AND created_at::date = %(date)s) AS recommendations_generated,
    (SELECT COUNT(*) FROM fact_recommendations
     WHERE recommended_at::date = %(date)s) AS destinations_recommended,
    (SELECT COUNT(*) FROM fact_recommendations
     WHERE recommended_at::date = %(date)s AND was_selected) AS destinations_selected,
    (SELECT COUNT(*) FROM fact_recommendations
     WHERE recommended_at::date = %(date)s AND was_saved) AS destinations_saved,
    (SELECT COUNT(*) FROM analytics_event
     WHERE event_type = 'signup_started' AND created_at::date = %(date)s) AS signups_started,
    (SELECT COUNT(*) FROM analytics_event
     WHERE event_type = 'user_registered' AND created_at::date = %(date)s) AS signups_completed,
    (SELECT COUNT(*) FROM analytics_event
     WHERE event_type = 'anonymous_user_authenticated' AND created_at::date = %(date)s) AS anonymous_visitors_authenticated,
    (SELECT COUNT(*) FROM fact_feedback
     WHERE created_at::date = %(date)s) AS feedback_submitted,
    (SELECT COUNT(*) FROM fact_feedback
     WHERE created_at::date = %(date)s AND rating >= 8) AS feedback_positive,
    (SELECT COUNT(*) FROM fact_ai_requests
     WHERE created_at::date = %(date)s) AS ai_requests_total,
    (SELECT COUNT(*) FROM fact_ai_requests
     WHERE created_at::date = %(date)s AND success = false) AS ai_requests_failed,
    (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) FROM fact_ai_requests
     WHERE created_at::date = %(date)s) AS ai_latency_p50_ms,
    (SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) FROM fact_ai_requests
     WHERE created_at::date = %(date)s) AS ai_latency_p95_ms,
    (SELECT percentile_cont(0.99) WITHIN GROUP (ORDER BY latency_ms) FROM fact_ai_requests
     WHERE created_at::date = %(date)s) AS ai_latency_p99_ms;
