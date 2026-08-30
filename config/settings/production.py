"""Production settings.

Per 11_SECURITY_&_PRIVACY.md and 12_DEVELOPMENT_&_DEPLOYMENT.md: production
must use secure configuration, HTTPS, and environment-provided secrets.
This module intentionally fails fast if ALLOWED_HOSTS is not configured.
"""

from .base import *  # noqa: F401,F403

DEBUG = False

# Render sets this automatically for any service with a public URL - added
# to ALLOWED_HOSTS so the very first deploy works before a custom domain
# (or an explicit DJANGO_ALLOWED_HOSTS override) exists. A no-op on any
# other host, since the env var simply won't be set there.
render_hostname = env("RENDER_EXTERNAL_HOSTNAME", default="")
if render_hostname and render_hostname not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(render_hostname)

if not ALLOWED_HOSTS:
    raise RuntimeError("DJANGO_ALLOWED_HOSTS must be set in production.")

if not SECRET_KEY or SECRET_KEY == "unsafe-development-key-change-me":
    raise RuntimeError("DJANGO_SECRET_KEY must be set in production.")

SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
# Render (like most PaaS platforms) terminates TLS at a proxy in front of
# the app - gunicorn only ever sees plain HTTP. Without this, Django can't
# tell the original request was HTTPS, and SECURE_SSL_REDIRECT above would
# redirect every request in an infinite loop (redirect to HTTPS -> proxy
# forwards as HTTP again -> redirect...).
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
CSRF_TRUSTED_ORIGINS = [f"https://{host}" for host in ALLOWED_HOSTS]
SECURE_HSTS_SECONDS = env.int("DJANGO_SECURE_HSTS_SECONDS", default=3600)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
