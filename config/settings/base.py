"""
Base Django settings for Wanderes.

Shared by every environment. Environment-specific overrides live in
development.py, production.py, and test.py.

Anything that differs between environments - secrets, hosts, debug flags -
comes from env vars. Never hardcode it, never commit it.
"""

from datetime import timedelta
from pathlib import Path

import environ
from celery.schedules import crontab

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
env_file = BASE_DIR / ".env"
if env_file.exists():
    environ.Env.read_env(env_file)

SECRET_KEY = env("DJANGO_SECRET_KEY", default="unsafe-development-key-change-me")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])

# The one hostname we build canonical/OG/sitemap/robots URLs from - never
# from request.get_host(). The site answers on a few different hostnames
# (apex, www, an old legacy one), and echoing back whatever a crawler
# happened to hit would just hand Google duplicate-content URLs instead
# of one clean signal. CanonicalDomainRedirectMiddleware does the matching
# 301 at the HTTP level too.
#
# Has to be www, not the bare apex - something outside this app already
# redirects the apex to www, and pointing this the other way caused a
# real infinite-redirect outage once. Don't flip this back without
# confirming live that nothing upstream still redirects apex -> www.
SITE_DOMAIN = env("SITE_DOMAIN", default="www.wanderes.com")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # django-allauth needs this (see SITE_ID below) - we don't otherwise
    # use multi-site support.
    "django.contrib.sites",
    "core",
    "users",
    "travel",
    "trips",
    "integrations",
    "ai",
    "recommendations",
    "analytics",
    # allauth adds Google login on top of the existing email/password flow
    # (users.forms.UserRegistrationForm etc.) - doesn't replace it. See the
    # ACCOUNT_*/SOCIALACCOUNT_* settings below for the wiring.
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
]

# Custom user model, email login, no username - see users/models.py.
# Changing this once real users exist means a real migration plan, so
# don't touch it casually.
AUTH_USER_MODEL = "users.User"

# django.contrib.sites wants this; we only ever have one site. Its
# `domain` field gets kept in sync with SITE_DOMAIN by a data migration
# over in users/migrations.
SITE_ID = 1

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Right after SecurityMiddleware on purpose - redirects legacy
    # hostnames onto SITE_DOMAIN before session lookup/locale detection do
    # any wasted work on a request that's about to bounce anyway. Only
    # touches a small allowlist, never Render's healthcheck hostname (see
    # the middleware's own docstring).
    "core.middleware.CanonicalDomainRedirectMiddleware",
    # Serves collected static files straight from the app process - the
    # simplest option for a small app on a managed PaaS, no CDN/nginx
    # needed. Has to sit right after SecurityMiddleware per whitenoise's
    # own docs.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Overrides LocaleMiddleware's cookie/Accept-Language guess when a
    # logged-in visitor has an explicit saved preference. Has to come
    # after both AuthenticationMiddleware (needs request.user) and
    # LocaleMiddleware (we're overriding its result).
    "core.middleware.UserLanguagePreferenceMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # allauth wants this as of its 0.65 series.
    "allauth.account.middleware.AccountMiddleware",
]

# ModelBackend still handles regular email/password login unchanged;
# allauth's backend only gets consulted for social logins.
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

# django-allauth config (Google OAuth login).
#
# users.models.User has no username field - login is email-only, matching
# the existing users:login/users:register flow. LOGIN_URL/
# LOGIN_REDIRECT_URL further below already point where we want; allauth
# honors those same settings, no need for its own ACCOUNT_LOGIN_REDIRECT_URL.
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*"]
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_EMAIL_VERIFICATION = "none"
# Skips allauth's own "confirm your email" interstitial for a first
# Google sign-in - Google already handed us a verified email, no need to
# make the traveler click through another step.
SOCIALACCOUNT_AUTO_SIGNUP = True
# Skips allauth's "you're about to sign in with Google" landing page too -
# straight to Google's own consent screen instead.
SOCIALACCOUNT_LOGIN_ON_GET = True
# Someone who registered with email/password and later hits "Sign in with
# Google" using the same address should land in their existing account,
# not a "this email is already in use" dead end or a silent duplicate
# account. Safe to trust because Google only ever returns a verified
# email for this scope.
SOCIALACCOUNT_EMAIL_AUTHENTICATION = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True
SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "SCOPE": ["profile", "email"],
        "AUTH_PARAMS": {"access_type": "online"},
        # Configured from env vars, not a DB-stored SocialApp row - same
        # pattern as every other provider setting here. Real values are a
        # manual step on the user's own Google Cloud project (see
        # DECISIONS_PENDING.md); left blank, the Google button just
        # doesn't show up.
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
                "core.context_processors.language_suggestion",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Postgres is where the real data lives.
DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="postgres://wanderes:wanderes@localhost:5432/wanderes",
    )
}

# Redis handles caching, rate limiting, and the job queue - never a source
# of truth for anything we'd be sad to lose.
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

# Climate cache pre-warming - see integrations.tasks.warm_climate_cache
# for why. Plain timedelta, not a crontab: "every 3 days" regardless of
# calendar day, comfortably inside the 7-day cache TTL so a real request
# shouldn't hit a cold cache. No django-celery-beat needed for one fixed
# schedule. Runs inside the worker process itself (`celery worker -B`) -
# fine with exactly one worker instance, but a second one would
# double-schedule this. Revisit if we ever scale the worker out.
CELERY_BEAT_SCHEDULE = {
    "warm-climate-cache": {
        "task": "integrations.tasks.warm_climate_cache",
        "schedule": timedelta(days=3),
    },
    # Recomputes yesterday's DailyProductMetrics. Crontab, not an interval
    # - "once a day" here means a specific time, not just N days since the
    # worker last restarted. Can queue behind warm-climate-cache on the
    # free tier's 2-concurrency limit; fine, Celery queues rather than
    # drops, this was never meant to be exact-time.
    "refresh-daily-product-metrics": {
        "task": "analytics.tasks.refresh_daily_metrics",
        "schedule": crontab(hour=2, minute=0),
    },
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# English stays the default (LANGUAGE_CODE, and the fallback for an
# unrecognized Accept-Language) - LocaleMiddleware picks a language per
# request from the switcher's cookie or the browser header.
#
# Names below are each language's own native name, not translated into
# whatever's currently active - someone landing on an English page still
# needs to spot "Português" in the switcher.
LANGUAGE_CODE = "en-us"
LANGUAGES = [
    ("en", "English"),
    ("pt", "Português"),
    ("es", "Español"),
    ("de", "Deutsch"),
    ("it", "Italiano"),
    ("fr", "Français"),
]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
# production.py's hashed-manifest storage needs collectstatic to have
# already run, which only happens in the prod Docker stage - plain
# storage here so {% static %} still works locally without one.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "users:login"
LOGIN_REDIRECT_URL = "users:account"
LOGOUT_REDIRECT_URL = "users:login"

# Picks the adapter behind integrations.climate.get_climate_provider().
# Open-Meteo for now, kept swappable.
CLIMATE_PROVIDER = env("CLIMATE_PROVIDER", default="open_meteo")

# Picks the adapter behind ai.provider.get_ai_provider(). OpenAI for now,
# kept swappable.
AI_PROVIDER = env("AI_PROVIDER", default="openai")
AI_MODEL = env("AI_MODEL", default="gpt-4o-mini")
OPENAI_API_KEY = env("OPENAI_API_KEY", default="")

# Picks the adapter behind integrations.flights.get_flight_provider().
# Blank on purpose - integrations/flights/kayak.py is still a skeleton
# (KAYAK's API needs manual business approval we don't have yet).
# get_flight_provider() raises a friendly error if something tries to use
# this before it's set.
FLIGHT_PROVIDER = env("FLIGHT_PROVIDER", default="")

# Same idea for integrations.hotels.get_hotel_provider() - no adapter is
# registered right now. Booking.com was ruled out (no property-level data
# feed available to Wanderes's publisher category - DECISIONS_PENDING.md
# §4); nothing else has been chosen yet.
HOTEL_PROVIDER = env("HOTEL_PROVIDER", default="")

# CJ Affiliate personal access token - authenticates against CJ's own
# developer API (link/product search, commission reporting). This is NOT
# Booking.com's Demand API; CJ approval doesn't grant that, and CJ
# confirmed no property-level feed exists for our publisher category
# either way. Powers integrations/affiliates/CJAffiliateProvider's
# deep-link generation.
CJ_API_TOKEN = env("CJ_API_TOKEN", default="")

# CJ Website ID / Property ID - a separate credential from the token
# above, tied to which registered CJ "website" a generated link gets
# attributed to. Get it from Account > Websites in the CJ dashboard.
# CJAffiliateProvider raises a clear config error if this is missing.
CJ_WEBSITE_ID = env("CJ_WEBSITE_ID", default="")

# Picks the adapter behind
# integrations.affiliates.get_affiliate_network_provider() - same pattern
# as the other provider settings above. "cj" is the one real adapter so
# far, using CJ's own Link Search API - still not Booking.com's Demand
# API, don't assume this unlocks live hotel search.
AFFILIATE_PROVIDER = env("AFFILIATE_PROVIDER", default="")

# Password-reset email, via Purelymail - EMAIL_HOST/PORT/USE_TLS below
# default to its real settings (see .env.example). EMAIL_HOST_USER is the
# actual signal real credentials exist, since EMAIL_HOST alone has a real
# default now. Without a real user we fall back to Django's console
# backend, which never raises and never delivers anything - so a
# password-reset request still "succeeds" from the visitor's side (same
# as Django's own never-reveal-account-existence convention) instead of
# failing SMTP auth against a host with no mailbox behind it. The
# "Forgot your password?" link itself stays hidden until this is
# genuinely wired up - see email_configured in core.context_processors.
EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
if EMAIL_HOST and EMAIL_HOST_USER:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_PORT = env.int("EMAIL_PORT", default=587)
    EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
    EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Wanderes <noreply@wanderes.com>")

# How long a password-reset token stays valid - kept short (Django's
# default is 3 days) since it's a single-use, security-sensitive link.
PASSWORD_RESET_TIMEOUT = 60 * 60 * 24

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
