-- fact_feedback
--
-- Grain: one row per trips.Feedback.
-- Primary key: feedback_id.
-- Source: trips_feedback directly - deliberately NOT the analytics event
--   log's feedback_submitted rows. The operational table already has
--   strictly more fidelity (rating, tags, real destination/trip FKs,
--   comment - excluded here on purpose, same "never duplicate free text
--   into analytics" principle analytics.models.Event's own docstring
--   already states) than the event's thin metadata, so it's the better
--   source whenever the entity already persists somewhere. Not every
--   fact should source from the event log - only behavior that has no
--   other home should.
-- Resolves destination via trip.destination when Feedback.destination is
--   null - trips_feedback's own feedback_has_destination_or_trip CHECK
--   constraint guarantees at least one is always set.
-- Update frequency: live.
CREATE VIEW fact_feedback AS
SELECT
    f.id AS feedback_id,
    f.user_id,
    COALESCE(f.destination_id, t.destination_id) AS destination_id,
    d.slug AS destination_slug,
    f.rating,
    f.tags,
    f.trip_id,
    f.created_at
FROM trips_feedback f
LEFT JOIN trips_trip t ON t.id = f.trip_id
LEFT JOIN travel_destination d ON d.id = COALESCE(f.destination_id, t.destination_id);
