-- fact_acquisition_funnel
--
-- Grain: one row per (conversation_key, episode_number, touch_type) -
--   touch_type is 'first' or 'latest'. Almost every episode has exactly
--   one acquisition_captured event (first_touch, captured once per
--   session and never overwritten) - a second row for the same episode
--   only appears if the same visitor clicked a genuinely new UTM-bearing
--   campaign link again within the same 30-minute inactivity window (a
--   real but rare case; see episode-splitting in int_event_episodes).
-- Primary key: id (md5 hash of the grain).
-- Source: int_event_episodes, correlating each acquisition_captured
--   event against later travel_question_submitted/recommendation_
--   generated/accommodation_outbound_click events in the SAME episode.
-- Business meaning: did this acquisition touch (source/medium/campaign/
--   content) lead to planning, a recommendation, or an accommodation-
--   search click? The basis for the acquisition funnel - see
--   analytics.queries for the actual rate calculations.
-- Update frequency: live.
CREATE VIEW fact_acquisition_funnel AS
WITH touches AS (
    SELECT
        conversation_key,
        episode_number,
        created_at,
        metadata ->> 'touch_type' AS touch_type,
        metadata ->> 'source' AS source,
        metadata ->> 'medium' AS medium,
        metadata ->> 'campaign' AS campaign,
        metadata ->> 'content' AS content,
        metadata ->> 'term' AS term
    FROM int_event_episodes
    WHERE event_type = 'acquisition_captured'
)
SELECT
    md5(t.conversation_key || ':' || t.episode_number::text || ':' || t.touch_type) AS id,
    t.conversation_key,
    t.episode_number,
    t.touch_type,
    t.source,
    t.medium,
    t.campaign,
    t.content,
    t.term,
    t.created_at AS touched_at,
    EXISTS (
        SELECT 1 FROM int_event_episodes e
        WHERE e.conversation_key = t.conversation_key
          AND e.episode_number = t.episode_number
          AND e.event_type = 'travel_question_submitted'
    ) AS reached_planning,
    EXISTS (
        SELECT 1 FROM int_event_episodes e
        WHERE e.conversation_key = t.conversation_key
          AND e.episode_number = t.episode_number
          AND e.event_type = 'recommendation_generated'
    ) AS reached_recommendation,
    EXISTS (
        SELECT 1 FROM int_event_episodes e
        WHERE e.conversation_key = t.conversation_key
          AND e.episode_number = t.episode_number
          AND e.event_type = 'accommodation_outbound_click'
    ) AS reached_accommodation_click
FROM touches t;
