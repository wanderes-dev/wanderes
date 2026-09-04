FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# gettext (2026-09-04, translation rollout) - provides msgfmt/msguniq,
# needed to run `manage.py compilemessages`/`makemessages` locally. Not
# needed at runtime by the deployed app itself - compiled .mo catalogs
# are committed to the repo alongside their .po sources (see locale/),
# generated once here rather than as a new production build step, given
# this same day's earlier lesson about untested deploy-time assumptions.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 gettext \
    && rm -rf /var/lib/apt/lists/*

FROM base AS builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements/ requirements/
RUN pip install --no-cache-dir --user -r requirements/development.txt

# Local development / test image (docker-compose.yml pins target: runtime for
# the web/worker services) - includes dev tools (pytest, ruff), runs the dev
# server. Never used for a real deploy.
FROM base AS runtime

COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

COPY . .

EXPOSE 8000

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

FROM base AS production-builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements/ requirements/
RUN pip install --no-cache-dir --user -r requirements/production.txt

# Deployable image (Phase 18 deploy prep, 2026-08-30) - leaner than `runtime`
# (no pytest/ruff), runs under gunicorn. This is the LAST stage on purpose:
# a plain `docker build .` (what most hosting platforms, incl. Render, run
# by default with no --target flag) builds this stage, not `runtime`.
FROM base AS production

COPY --from=production-builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH \
    DJANGO_SETTINGS_MODULE=config.settings.production

COPY . .

# Must run under `production` settings specifically - that's the only
# settings module using whitenoise's hashed-manifest static storage, and
# the manifest it generates here is exactly what the real runtime process
# (also under `production`) needs to find later. Throwaway values satisfy
# production.py's fail-fast ALLOWED_HOSTS/SECRET_KEY checks at build time
# only - the real runtime container gets its real values from the
# platform's env vars, not from this layer.
RUN DJANGO_ALLOWED_HOSTS=build.invalid DJANGO_SECRET_KEY=build-time-only-unused-at-runtime \
    python manage.py collectstatic --noinput

EXPOSE 8000

# Shell form (not exec-array) so $PORT expands - hosting platforms (e.g.
# Render) inject the port to bind at runtime; 8000 is the local fallback.
CMD ["sh", "-c", "gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000}"]
