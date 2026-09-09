-- fact_ai_requests
--
-- Grain: one row per llm_request_completed / provider_request_completed
--   analytics_event.
-- Primary key: event_id.
-- Source: analytics_event.
-- Business meaning: AI/provider call reliability and latency - the
--   source for failure rate and p50/p95/p99 latency (via Postgres's
--   native percentile_cont, computed live - no separate library needed).
--   Deliberately no token/model/cost data this pass - see
--   analytics.instrumentation's own module docstring for exactly why,
--   and documentation/16_ANALYTICS_ARCHITECTURE.md for the documented
--   future path to real cost metrics.
-- Update frequency: live.
CREATE VIEW fact_ai_requests AS
SELECT
    id AS event_id,
    event_type,
    metadata ->> 'operation' AS operation,
    (metadata ->> 'success')::boolean AS success,
    (metadata ->> 'latency_ms')::numeric AS latency_ms,
    metadata ->> 'error_type' AS error_type,
    conversation_key,
    created_at
FROM analytics_event
WHERE event_type IN ('llm_request_completed', 'provider_request_completed');
