-- dim_destinations
--
-- Grain: one row per travel.Destination.
-- Primary key: destination_id.
-- Source: travel_destination, left-joined to travel_countryentryrequirement
--   (matched by country) for has_video.
-- Business meaning: the canonical destination dimension for analytics -
--   real fields only, no invented facts (05_AI_DESIGN.md §7's "never
--   invent travel data" applies to analytics surfaces too, not just the
--   AI's own replies).
-- Update frequency: live.
CREATE VIEW dim_destinations AS
SELECT
    d.id AS destination_id,
    d.slug,
    d.name,
    d.country,
    d.trip_type,
    d.cost_of_living,
    COALESCE(jsonb_array_length(cer.videos) > 0, false) AS has_video,
    d.created_at
FROM travel_destination d
LEFT JOIN travel_countryentryrequirement cer ON cer.country = d.country;
