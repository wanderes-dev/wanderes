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
--   was_accommodation_clicked = the traveler clicked the "Search stays"
--   Booking.com link on it later in the same episode. Unlike was_selected/
--   was_saved, this one is attributed to the NEAREST preceding
--   recommendation only (no other recommendation of the same destination
--   exists between this row and the click) - a click is a single,
--   deliberate action on one destination, so letting it fan out and mark
--   every earlier recommendation of that destination in the episode
--   as "clicked" would silently double- (or triple-, ...) count it in any
--   COUNT(*)-based click/CTR aggregation. was_selected/was_saved keep
--   their original any-later-event correlation (documented as an
--   accepted edge case below) - not touched by this change, since
--   changing their semantics wasn't asked for and duplicate rows for one
--   destination are already an existing, separate, documented limitation
--   of this view (see the grain note above).
--
-- Deliberately an APPROXIMATE, session-based correlation, not a hard
-- foreign key: minting a real recommendation_id and threading it through
-- the "Choose this trip"/"Save this trip" UI (query params, a hidden
-- form field, a new column on Trip) would be a much larger, riskier
-- change than this pass's actual value justifies. A traveler recommending
-- the same destination to themselves twice in one episode, or acting on
-- it out of the order this correlation assumes, are known, accepted
-- edge cases for was_selected/was_saved - see
-- documentation/16_ANALYTICS_ARCHITECTURE.md.
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
    ) AS was_saved,
    EXISTS (
        SELECT 1 FROM int_event_episodes e
        WHERE e.conversation_key = r.conversation_key
          AND e.episode_number = r.episode_number
          AND e.event_type = 'accommodation_outbound_click'
          AND e.metadata ->> 'destination_slug' = r.destination_slug
          AND e.created_at > r.created_at
          -- Only attribute the click to the nearest preceding
          -- recommendation of this destination - if a later, more recent
          -- recommendation of the same destination exists between this
          -- row and the click, that later row is the correct one to
          -- credit, not this one.
          AND NOT EXISTS (
              SELECT 1 FROM recommended r2
              WHERE r2.conversation_key = r.conversation_key
                AND r2.episode_number = r.episode_number
                AND r2.destination_slug = r.destination_slug
                AND r2.created_at > r.created_at
                AND r2.created_at < e.created_at
          )
    ) AS was_accommodation_clicked
FROM recommended r;
