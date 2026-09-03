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
    # Required by django-allauth (SITE_ID below) - not otherwise used by
    # this app, which has never needed multi-site support.
    "django.contrib.sites",
    "core",
    "users",
    "travel",
    "trips",
    "integrations",
    "ai",
    "recommendations",
    "analytics",
    # Google OAuth login (2026-09-03, direct user request). allauth is
    # additive to the existing email/password login (users.forms.
    # UserRegistrationForm, users.views.register/login) - it does not
    # replace it. See the ACCOUNT_*/SOCIALACCOUNT_* settings below for how
    # it's wired to the custom email-only User model.
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
]

# Custom user model (email login, no username field) — see users/models.py.
# Must be set before the first migration; do not change once real user
# data exists without a data migration plan.
AUTH_USER_MODEL = "users.User"

# django.contrib.sites requires this; only one site ever exists here. The
# Site row's own `domain` field is kept in sync with SITE_DOMAIN by a data
# migration (users/migrations - see its own comment for why it lives
# there rather than in a new app just for this).
SITE_ID = 1

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
    # Required by django-allauth as of its 0.65 series (2026-09-03).
    "allauth.account.middleware.AccountMiddleware",
]

# django.contrib.auth's default ModelBackend still handles the existing
# email/password login (users.forms.UserRegistrationForm) unchanged;
# allauth's backend is additive, only ever consulted for social logins.
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

# django-allauth configuration (2026-09-03, Google OAuth login).
#
# The User model (users.models.User) has no username field at all - login
# is email-only, matching how users:login/users:register already work.
# LOGIN_URL/LOGIN_REDIRECT_URL (defined once, further below) already point
# at users:login/users:account - allauth reads and honors both of those
# same settings, no separate ACCOUNT_LOGIN_REDIRECT_URL needed.
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*"]
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_EMAIL_VERIFICATION = "none"
# Skips allauth's own intermediate "confirm your email/finish signup" page
# entirely for a first-time Google sign-in - the account is created
# straight from the verified email Google already provided, matching the
# low-friction "never make the traveler do more than necessary" pattern
# already used elsewhere in this app (e.g. the chat's conversational
# feedback/future-intent capture). Safe specifically because Google
# itself only ever hands back a verified email for the "email" scope.
SOCIALACCOUNT_AUTO_SIGNUP = True
# Skips allauth's own intermediate "you are about to sign in with Google"
# landing page - the Google button goes straight to Google's consent
# screen, the only screen with real content the traveler needs to see.
SOCIALACCOUNT_LOGIN_ON_GET = True
# A traveler who already registered with email/password and later clicks
# "Sign in with Google" using the same address should land in their
# existing account, not hit a "this email is already in use" dead end or
# silently create a second, disconnected account - safe to trust here
# specifically because Google only ever returns a verified email for this
# scope (the same reasoning as SOCIALACCOUNT_AUTO_SIGNUP above).
SOCIALACCOUNT_EMAIL_AUTHENTICATION = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True
SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "SCOPE": ["profile", "email"],
        "AUTH_PARAMS": {"access_type": "online"},
        # Configured entirely from settings/env vars, never a DB-stored
        # SocialApp row via the admin - matches this project's existing
        # pattern for every other external provider (OPENAI_API_KEY,
        # CLIMATE_PROVIDER, etc.). Both real values are a manual step tied
        # to the user's own Google Cloud Console project - see
        # DECISIONS_PENDING.md and .env.example for what's needed and
        # where to get it. Left blank, Google login simply isn't offered
        # as a working option yet; nothing else about the app depends on
        # these being set.
        "APP": {
            "client_id": env("GOOGLE_OAUTH_CLIENT_ID", default=""),
            "secret": env("GOOGLE_OAUTH_CLIENT_SECRET", default=""),
            "key": "",
        },
    }
}

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
