from django.conf import settings
from django.db import migrations


def set_site_domain(apps, schema_editor):
    """Points django.contrib.sites's default Site row (id=1, matching
    settings.SITE_ID) at the app's real canonical domain instead of the
    framework's own "example.com" placeholder (2026-09-03, added
    alongside django-allauth for Google OAuth login - allauth is the
    reason this project needs django.contrib.sites at all). Reads
    settings.SITE_DOMAIN - the same single source of truth already used
    for canonical/OG/sitemap URLs - so the two can never silently drift
    apart."""
    Site = apps.get_model("sites", "Site")
    Site.objects.update_or_create(
        id=settings.SITE_ID,
        defaults={"domain": settings.SITE_DOMAIN, "name": "Wanderes"},
    )


def reverse_noop(apps, schema_editor):
    # Deliberately not restoring "example.com" - there's no meaningful
    # "undo" for this, and leaving the real domain in place on a rollback
    # is harmless.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0003_travelerprofile_budget_currency"),
        ("sites", "0002_alter_domain_unique"),
    ]

    operations = [
        migrations.RunPython(set_site_domain, reverse_noop),
    ]
