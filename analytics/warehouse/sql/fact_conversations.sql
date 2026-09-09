-- fact_conversations
--
-- Grain: one row per (conversation_key, episode_number) - a single real
--   conversation episode. See int_event_episodes for why episode_number
--   (not bare conversation_key) is the right grain.
-- Primary key: id (a stable md5 hash of conversation_key + episode_number
--   - Postgres views have no real PK constraint of their own, this exists
--   only so the Django unmanaged model mapped onto this view has a
--   genuinely unique field to use as one).
-- Source: int_event_episodes.
-- Business meaning: how far one conversation got - message count, and
--   whether it reached a recommendation, a "Choose this trip" selection,
--   a saved trip, or feedback. The basis for the conversation funnel.
-- Update frequency: live.
CREATE VIEW fact_conversations AS
SELECT
    md5(conversation_key || ':' || episode_number::text) AS id,
    conversation_key,
    episode_number,
    MIN(created_at) AS started_at,
    MAX(created_at) AS last_event_at,
    MAX(user_id) AS user_id,
    (ARRAY_AGG(locale ORDER BY created_at) FILTER (WHERE locale != ''))[1] AS locale,
    COUNT(*) FILTER (WHERE event_type = 'travel_question_submitted') AS message_count,
    BOOL_OR(event_type = 'recommendation_generated') AS reached_recommendation,
    BOOL_OR(event_type = 'destination_selected') AS reached_selection,
    BOOL_OR(event_type = 'trip_created') AS reached_trip_created,
    BOOL_OR(event_type = 'feedback_submitted') AS reached_feedback
FROM int_event_episodes
WHERE event_type IN (
    'travel_question_submitted',
    'recommendation_generated',
    'destination_selected',
    'trip_created',
    'feedback_submitted'
)
GROUP BY conversation_key, episode_number;
