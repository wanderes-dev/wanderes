"""Celery application for TravelAgent background processing.

Per 03_SYSTEM_ARCHITETURE.md, Redis backs the background job queue and no
tasks are defined yet at this stage of the project (Milestone 1 only
establishes the infrastructure). Real background jobs are introduced later,
per 15_IMPLEMENTATION_GUIDE.md Phase 16, only when a specific need justifies
them.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

app = Celery("travelagent")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@app.task(bind=True)
def debug_task(self):
    print(f"Request: {self.request!r}")
