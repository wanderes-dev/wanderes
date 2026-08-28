"""Settings used by the automated test suite (pytest-django / CI)."""

from .base import *  # noqa: F401,F403

DEBUG = False
SECRET_KEY = "test-secret-key"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
CELERY_TASK_ALWAYS_EAGER = True
