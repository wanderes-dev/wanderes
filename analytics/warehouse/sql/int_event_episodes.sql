-- int_event_episodes
--
-- Grain: one row per analytics_event that has a conversation_key.
-- Primary key: event_id.
-- Source: analytics_event.
-- Business meaning: every chat-related event, augmented with a real
--   per-conversation episode_number. Not meant to be queried directly by
--   a dashboard - it exists purely so fact_conversations and
--   fact_recommendations can both build on the same sessionization logic
--   without duplicating it.
-- Update frequency: live (a plain view, recomputed on every query - no
--   materialization needed at current data volume).
--
-- Why this exists at all: ai.memory.conversation_key() returns the SAME
-- string for an authenticated user's entire lifetime of chat activity
-- (chat-history:user:{pk}), never a per-visit value - it's correct for
-- its actual purpose (cross-device short-term memory continuity) but is
-- NOT a per-conversation identifier. Splitting on a 30-minute inactivity
-- gap - the exact TTL ai.memory's own Redis-backed state already uses -
-- recovers real conversation episodes from it. Without this split, every
-- authenticated user's entire chat history would silently collapse into
-- one "conversation," corrupting any funnel or recommendation-correlation
-- metric for exactly the retained-user segment that matters most.
CREATE VIEW int_event_episodes AS
WITH lagged AS (
    SELECT
        id,
        conversation_key,
        user_id,
        locale,
        event_type,
        metadata,
        created_at,
        LAG(created_at) OVER (
            PARTITION BY conversation_key ORDER BY created_at
        ) AS prev_created_at
    FROM analytics_event
    WHERE conversation_key IS NOT NULL
)
SELECT
    id AS event_id,
    conversation_key,
    user_id,
    locale,
    event_type,
    metadata,
    created_at,
    SUM(
        CASE
            WHEN prev_created_at IS NULL
                OR created_at - prev_created_at > INTERVAL '30 minutes'
            THEN 1
            ELSE 0
        END
    ) OVER (PARTITION BY conversation_key ORDER BY created_at) AS episode_number
FROM lagged;
