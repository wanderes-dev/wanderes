"""Production settings.

Per 11_SECURITY_&_PRIVACY.md and 12_DEVELOPMENT_&_DEPLOYMENT.md: production
must use secure configuration, HTTPS, and environment-provided secrets.
This module intentionally fails fast if ALLOWED_HOSTS is not configured.
"""

from .base import *  # noqa: F401,F403

DEBUG = False

if not ALLOWED_HOSTS:
    raise RuntimeError("DJANGO_ALLOWED_HOSTS must be set in production.")

if not SECRET_KEY or SECRET_KEY == "unsafe-development-key-change-me":
    raise RuntimeError("DJANGO_SECRET_KEY must be set in production.")

SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = env.int("DJANGO_SECURE_HSTS_SECONDS", default=3600)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
