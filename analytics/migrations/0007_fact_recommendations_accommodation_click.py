"""Adds was_accommodation_clicked to fact_recommendations (2026-09-23,
Booking.com accommodation search + CJ affiliate attribution feature) - see
analytics/warehouse/sql/fact_recommendations.sql for the current
definition. Reads the current (already-updated) .sql file for the forward
SQL, same as 0003_create_warehouse_views.py; the reverse SQL is the
previous definition inlined directly, since the .sql file itself no longer
has it.
"""

from pathlib import Path

from django.db import migrations

SQL_DIR = Path(__file__).resolve().parent.parent / "warehouse" / "sql"

_PREVIOUS_VIEW_SQL = """
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
"""


class Migration(migrations.Migration):
    dependencies = [
        ("analytics", "0006_alter_event_event_type"),
    ]

    operations = [
        migrations.RunSQL(
            sql="DROP VIEW fact_recommendations;\n"
            + (SQL_DIR / "fact_recommendations.sql").read_text(encoding="utf-8"),
            reverse_sql="DROP VIEW fact_recommendations;\n" + _PREVIOUS_VIEW_SQL,
        ),
    ]
