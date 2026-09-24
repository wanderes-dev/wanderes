"""Creates fact_acquisition_funnel (2026-09-24, first-party acquisition
attribution) - see analytics/warehouse/sql/fact_acquisition_funnel.sql for
the view's own documented grain/primary key/source/business meaning, and
analytics/warehouse/models.py for the Django model mapped onto it. Same
"read the .sql file, don't duplicate it inline" pattern as
0003_create_warehouse_views.py.
"""

from pathlib import Path

from django.db import migrations

SQL_DIR = Path(__file__).resolve().parent.parent / "warehouse" / "sql"


class Migration(migrations.Migration):
    dependencies = [
        ("analytics", "0008_factacquisitionfunnel_alter_event_event_type"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(SQL_DIR / "fact_acquisition_funnel.sql").read_text(encoding="utf-8"),
            reverse_sql="DROP VIEW IF EXISTS fact_acquisition_funnel;",
        ),
    ]
