"""Creates the read-only warehouse views (2026-09-09, analytics/data-
engineering pass) - see analytics/warehouse/sql/*.sql for each view's own
documented grain/primary key/source/business meaning, and
analytics/warehouse/models.py for the Django models mapped onto them.

Each view's SQL lives in its own .sql file (one source of truth, not
duplicated into this migration) - loaded here rather than inlined so the
file a reviewer actually reads for "what does this view do" is the same
file Postgres executes. Operations are listed in dependency order
(int_event_episodes first, since fact_conversations/fact_recommendations
both select from it); Django applies each operation's reverse_sql in
reverse list order when unmigrating, which is exactly the correct drop
order (dependents before dependencies) - no separate bookkeeping needed.
"""

from pathlib import Path

from django.db import migrations

SQL_DIR = Path(__file__).resolve().parent.parent / "warehouse" / "sql"


def _view_sql(name: str) -> tuple[str, str]:
    create_sql = (SQL_DIR / f"{name}.sql").read_text(encoding="utf-8")
    drop_sql = f"DROP VIEW IF EXISTS {name};"
    return create_sql, drop_sql


class Migration(migrations.Migration):
    dependencies = [
        ("analytics", "0002_event_conversation_key_event_locale_and_more"),
        ("travel", "0003_countryentryrequirement_videos"),
        ("users", "0005_user_preferred_language"),
        ("trips", "0005_alter_feedback_comment_alter_feedback_rating_and_more"),
    ]

    operations = [
        migrations.RunSQL(*_view_sql("int_event_episodes")),
        migrations.RunSQL(*_view_sql("dim_destinations")),
        migrations.RunSQL(*_view_sql("dim_users")),
        migrations.RunSQL(*_view_sql("fact_conversations")),
        migrations.RunSQL(*_view_sql("fact_recommendations")),
        migrations.RunSQL(*_view_sql("fact_ai_requests")),
        migrations.RunSQL(*_view_sql("fact_feedback")),
    ]
