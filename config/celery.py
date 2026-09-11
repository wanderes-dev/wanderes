"""Celery application for Wanderes background processing.

Redis backs the background job queue - see 03_SYSTEM_ARCHITETURE.md for
the broader design. New background jobs get added under
15_IMPLEMENTATION_GUIDE.md's guidance, only when a specific need
justifies them.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

app = Celery("wanderes")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@app.task(bind=True)
def debug_task(self):
    print(f"Request: {self.request!r}")
