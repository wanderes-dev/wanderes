-- fact_recommendations
--
-- Grain: one row per (conversation_key, episode_number, destination_slug)
--   - a single destination that was recommended within one conversation
--   episode, unnested from recommendation_generated's metadata
--   .destination_slugs array.
-- Primary key: id (a stable md5 hash of the three grain columns - see
--   fact_conversations for why).
-- Source: int_event_episodes (recommendation_generated events, unnested),
--   correlated against later destination_selected/trip_created events in
--   the SAME episode.
-- Business meaning: was this recommended destination acted on?
--   was_selected = the traveler clicked "Choose this trip" on it later in
--   the same episode. was_saved = it was later saved as a trip
--   (trip_created) in the same episode - covers both the "Save this
--   trip" chat link (source=chat_recommendation) and the conversational
--   future-intent capture path (source=chat), since both represent a
--   real positive outcome for this specific recommended destination.
--
-- Deliberately an APPROXIMATE, session-based correlation, not a hard
-- foreign key: minting a real recommendation_id and threading it through
-- the "Choose this trip"/"Save this trip" UI (query params, a hidden
-- form field, a new column on Trip) would be a much larger, riskier
-- change than this pass's actual value justifies. A traveler recommending
-- the same destination to themselves twice in one episode, or acting on
-- it out of the order this correlation assumes, are known, accepted
-- edge cases - see documentation/16_ANALYTICS_ARCHITECTURE.md.
-- Update frequency: live.
CREATE VIEW fact_recommendations AS
WITH recommended AS (
    SELECT
        conversation_key,
        episode_number,
        created_at,
        jsonb_array_elements_text(
            COALESCE(metadata -> 'destination_slugs', '[]'::jsonb)
        ) AS destination_slug
    FROM int_event_episodes
    WHERE event_type = 'recommendation_generated'
)
SELECT
    md5(r.conversation_key || ':' || r.episode_number::text || ':' || r.destination_slug) AS id,
    r.conversation_key,
    r.episode_number,
    r.destination_slug,
    r.created_at AS recommended_at,
    EXISTS (
        SELECT 1 FROM int_event_episodes e
        WHERE e.conversation_key = r.conversation_key
          AND e.episode_number = r.episode_number
          AND e.event_type = 'destination_selected'
          AND e.metadata ->> 'destination_slug' = r.destination_slug
          AND e.created_at > r.created_at
    ) AS was_selected,
    EXISTS (
        SELECT 1 FROM int_event_episodes e
        WHERE e.conversation_key = r.conversation_key
          AND e.episode_number = r.episode_number
          AND e.event_type = 'trip_created'
          AND e.metadata ->> 'destination_slug' = r.destination_slug
          AND e.created_at > r.created_at
    ) AS was_saved
FROM recommended r;
