"""
Base Django settings for Wanderes.

Shared by every environment. Environment-specific overrides live in
development.py, production.py, and test.py.

Per 03_SYSTEM_ARCHITETURE.md and 11_SECURITY_&_PRIVACY.md: configuration
that differs between environments (secrets, hosts, debug flags) must come
from environment variables, never be hardcoded, and must never be committed
to source control.
"""

from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
env_file = BASE_DIR / ".env"
if env_file.exists():
    environ.Env.read_env(env_file)

SECRET_KEY = env("DJANGO_SECRET_KEY", default="unsafe-development-key-change-me")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])

# The one canonical hostname search engines and social previews should ever
# see (2026-09-03, SEO prep) - used to build absolute canonical/Open Graph/
# sitemap/robots.txt URLs from a fixed value, deliberately never from
# request.get_host(). The live service is reachable under at least three
# hostnames (wanderes.com, www.wanderes.com, and the legacy
# travelagent-web.onrender.com - see PROJECT_STATE.md's Phase 18 entries) -
# echoing back whatever host a crawler happened to use would hand Google
# duplicate-content URLs for the same page instead of one consolidated
# signal. See core.middleware.CanonicalDomainRedirectMiddleware for the
# matching 301 redirect that keeps this true at the HTTP level too, not
# just in generated links.
#
# www.wanderes.com, not the bare apex (2026-09-03 production incident,
# same day this setting was introduced): something outside this app -
# confirmed live, not something in this codebase - already redirects
# wanderes.com to www.wanderes.com. The first version of this setting
# used the apex, and the matching middleware redirected www back to the
# apex - an infinite loop between that external redirect and this app's
# own, which took the entire public site down for several minutes. Do not
# change this back to the apex without first confirming, live, that
# nothing upstream still redirects apex to www.
SITE_DOMAIN = env("SITE_DOMAIN", default="www.wanderes.com")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
    "users",
    "travel",
    "trips",
    "integrations",
    "ai",
    "recommendations",
    "analytics",
]

# Custom user model (email login, no username field) — see users/models.py.
# Must be set before the first migration; do not change once real user
# data exists without a data migration plan.
AUTH_USER_MODEL = "users.User"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Consolidates duplicate hostnames onto SITE_DOMAIN before anything else
    # runs (2026-09-03, SEO prep) - deliberately placed first, right after
    # SecurityMiddleware, so a redirect never does wasted work (session
    # lookup, locale detection) for a request that's about to be redirected
    # anyway. Only ever touches a small explicit allowlist of known legacy
    # hostnames - never Render's own current healthcheck hostname - see the
    # middleware's own docstring for why that distinction matters.
    "core.middleware.CanonicalDomainRedirectMiddleware",
    # Serves collected static files directly from the app process (Phase 18
    # deploy prep, 2026-08-30) - simplest option for a small app on a
    # managed PaaS, no separate CDN/nginx needed (12_DEVELOPMENT_&_DEPLOYMENT.md
    # §15). Must stay directly after SecurityMiddleware per whitenoise's docs.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.site_meta",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# PostgreSQL is the source of truth for persistent business data.
# See 04_DATABASE_DESIGN.md.
DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="postgres://wanderes:wanderes@localhost:5432/wanderes",
    )
}

# Redis supports caching, rate limiting, and background job queues.
# It is never used as the source of truth for persistent business data.
REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}

CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)

# Climate cache pre-warming (2026-09-02, direct user request following a
# real reported timeout - see integrations.tasks.warm_climate_cache for
# the full reasoning). A plain timedelta schedule rather than a crontab -
# "every 3 days" regardless of calendar day, comfortably inside the
# climate provider's own 7-day cache TTL so a real user request should
# never hit a cold cache in normal operation. Uses Celery's built-in
# beat_schedule (no django-celery-beat dependency) since a single fixed
# schedule needs no runtime-editable UI. Run via the worker process
# itself (`celery worker -B`, see docker-compose.yml/render.yaml) rather
# than a separate beat service - correct only as long as exactly one
# worker instance is running; a second instance would double-schedule
# this task. Revisit if the worker is ever scaled beyond one instance.
CELERY_BEAT_SCHEDULE = {
    "warm-climate-cache": {
        "task": "integrations.tasks.warm_climate_cache",
        "schedule": timedelta(days=3),
    },
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# English is the only shipped language for now (product decision, 2026-08-29).
# USE_I18N + LOCALE_PATHS + LocaleMiddleware are already wired up so that
# adding another language later is a translation/config task, not a
# refactor: wrap user-facing strings in gettext/gettext_lazy (Python) or
# {% trans %}/{% blocktrans %} (templates) as they're written, and add the
# language to LANGUAGES + provide its .po files under locale/ when needed.
LANGUAGE_CODE = "en-us"
LANGUAGES = [
    ("en", "English"),
]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
# The compressed/hashed manifest storage (config/settings/production.py)
# requires collectstatic to have already run, which only happens in the
# production Docker stage - plain storage here so {% static %} works in
# local dev/test without needing a manifest.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "users:login"
LOGIN_REDIRECT_URL = "users:account"
LOGOUT_REDIRECT_URL = "users:login"

# Which climate provider adapter backs integrations.climate.get_climate_provider().
# Phase 3 decision: Open-Meteo, kept swappable per 10_EXTERNAL_INTEGRATIONS.md §3.
CLIMATE_PROVIDER = env("CLIMATE_PROVIDER", default="open_meteo")

# Which AI provider adapter backs ai.provider.get_ai_provider().
# Phase 2 decision: OpenAI, kept swappable per 05_AI_DESIGN.md §10.
AI_PROVIDER = env("AI_PROVIDER", default="openai")
AI_MODEL = env("AI_MODEL", default="gpt-4o-mini")
OPENAI_API_KEY = env("OPENAI_API_KEY", default="")

# Which flight provider adapter backs integrations.flights.get_flight_provider().
# 2026-09-02: interface scaffolded ahead of a concrete adapter (see
# DECISIONS_PENDING.md §4) - default blank on purpose, since
# integrations/flights/kayak.py is a deliberate skeleton, not a working
# adapter yet (KAYAK's API needs manual business approval Wanderes doesn't
# have). get_flight_provider() raises a clear, friendly error if something
# tries to use this before it's set.
FLIGHT_PROVIDER = env("FLIGHT_PROVIDER", default="")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "root": {
        "handlers": ["console"],
        "level": env("DJANGO_LOG_LEVEL", default="INFO"),
    },
}
