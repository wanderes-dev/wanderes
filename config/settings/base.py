"""
Base Django settings for TravelAgent.

Shared by every environment. Environment-specific overrides live in
development.py, production.py, and test.py.

Per 03_SYSTEM_ARCHITETURE.md and 11_SECURITY_&_PRIVACY.md: configuration
that differs between environments (secrets, hosts, debug flags) must come
from environment variables, never be hardcoded, and must never be committed
to source control.
"""

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
]

# Custom user model (email login, no username field) — see users/models.py.
# Must be set before the first migration; do not change once real user
# data exists without a data migration plan.
AUTH_USER_MODEL = "users.User"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
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
        default="postgres://travelagent:travelagent@localhost:5432/travelagent",
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
