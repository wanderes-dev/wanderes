-- dim_users
--
-- Grain: one row per users.User.
-- Primary key: user_id.
-- Source: users_user, left-joined to users_travelerprofile.
-- Business meaning: internal-use user dimension - date_joined/last_login
--   for tenure/activity context, preferred_language for locale analysis,
--   home_country for market analysis. Deliberately minimal: never
--   exposes email/password/name fields even though this is an
--   internal-only surface, since analytics genuinely has no need for
--   them (data minimization on principle, not because it's exposed
--   externally).
-- Update frequency: live.
CREATE VIEW dim_users AS
SELECT
    u.id AS user_id,
    u.date_joined,
    u.last_login,
    u.preferred_language,
    u.is_staff,
    tp.home_country,
    tp.preferred_cost_of_living,
    (tp.id IS NOT NULL) AS has_traveler_profile
FROM users_user u
LEFT JOIN users_travelerprofile tp ON tp.user_id = u.id;
