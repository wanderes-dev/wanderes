# Wanderes

Wanderes is an Intelligent Travel Consultant — not an AI trip planner, not a travel agency, not a booking platform. It helps travelers make better, more confident travel decisions through personalized, explainable recommendations.

Full product and architecture documentation lives in [`documentation/`](documentation/). Start with [`documentation/02_PROJECT_CONTEXT.md`](documentation/02_PROJECT_CONTEXT.md) for the project's purpose and working principles, and [`documentation/15_IMPLEMENTATION_GUIDE.md`](documentation/15_IMPLEMENTATION_GUIDE.md) for how development proceeds phase by phase.

Ongoing development is tracked in [`documentation/DEVELOPMENT_LOG.md`](documentation/DEVELOPMENT_LOG.md) (what's been built, in order) and [`documentation/PROJECT_STATE.md`](documentation/PROJECT_STATE.md) (exactly where implementation currently stands). Decisions that require human input before work can continue are listed in [`documentation/DECISIONS_PENDING.md`](documentation/DECISIONS_PENDING.md).

## Stack

- **Backend:** Django (modular monolith)
- **Database:** PostgreSQL (source of truth for persistent data)
- **Cache / queues:** Redis
- **Background jobs:** Celery
- **Frontend (initial):** Django templates + light JavaScript (no React yet — see `08_FRONTEND_ARCHITETURE.md`)

## Local Development (Docker — recommended)

Requires [Docker Desktop](https://www.docker.com/products/docker-desktop/).

```bash
cp .env.example .env
docker compose up --build
```

In another terminal, run migrations:

```bash
docker compose exec web python manage.py migrate
```

Then check the health endpoint at http://localhost:8000/health/ — it should return `{"status": "ok", "database": "ok"}`.

Run the test suite (the `-e` override matters — see `CLAUDE.md` for why a bare `docker compose exec web pytest` silently runs under the wrong settings module):

```bash
docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test web pytest
```

## Local Development (without Docker)

Only recommended if Docker is unavailable. Requires a local PostgreSQL and Redis instance.

```bash
python -m venv .venv
.venv\Scripts\activate       # Windows
pip install -r requirements/development.txt
cp .env.example .env          # then edit DATABASE_URL/REDIS_URL to use localhost
python manage.py migrate
python manage.py runserver
```

## Tests & Linting

```bash
pytest
ruff check .
```

## Project Structure

```
config/          Django project settings, URLs, WSGI/ASGI, Celery app
core/            Cross-cutting infrastructure (health check, shared utilities)
users/           Custom User (email login) and TravelerProfile
travel/          Destination model; `load_destinations` management command
trips/           Trip, TripFlight, TripAccommodation, Feedback
integrations/    External provider adapters (e.g. climate/ - Open-Meteo), no models
ai/              AI provider adapter (OpenAI), orchestration.py, the Wander system prompt, and the /chat/ page
recommendations/ Deterministic recommendation scoring/ranking, no models
documentation/   Product & architecture docs, development log, decision log
requirements/    Python dependencies (base / development / production)
```

The AI adapter needs a real `OPENAI_API_KEY` in `.env` to work at runtime (see `.env.example`) — without one it raises a clear configuration error rather than a cryptic SDK failure.

## Try it

Once the stack is running (see above) and `OPENAI_API_KEY` is set, open **http://localhost:8000/chat/** and talk to Wander.

Load the curated destination dataset (after migrating) with:

```bash
python manage.py load_destinations
```

## Deployment (Render)

Phase 18 (`15_IMPLEMENTATION_GUIDE.md`) needs the app in front of real users, which means it has to be reachable outside `localhost`. [`render.yaml`](render.yaml) is a [Render Blueprint](https://render.com/docs/blueprint-spec) declaring a web service, a Celery background worker, a managed Postgres database, and a managed Key Value (Redis) instance — the same four services `docker-compose.yml` runs locally, deployed for real.

**2026-09-02: resource names renamed `travelagent-*` → `wanderes-*`.** Render matches Blueprint resources to already-provisioned ones by their `name:` field, so this is not an in-place rename — the next Blueprint apply provisions brand-new `wanderes-web`/`wanderes-worker`/`wanderes-db`/`wanderes-redis` resources rather than renaming the existing `travelagent-*` ones, which stay orphaned (not auto-deleted) with all prior data. Done deliberately, with prior production data judged fine to lose. The steps below describe applying the Blueprint fresh under the new names — do the same steps in the Render dashboard (**New > Blueprint**) rather than trying to edit the existing services in place.

To deploy it:

1. Push this repo to GitHub (already done — `origin` → `wanderes-dev/wanderes`).
2. Before starting, generate one long random string to use as `DJANGO_SECRET_KEY` (needed twice in the next step — Render's Blueprint spec has no way to share a plain env var between services automatically, see the comment in `render.yaml`). Any of these work:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(50))"
   ```
3. In the Render dashboard, choose **New > Blueprint** and connect this repository. Render reads `render.yaml` and proposes the four `wanderes-*` services above.
4. During the Blueprint creation flow, Render prompts for every `sync: false` secret — fill in:
   - `OPENAI_API_KEY` (both `wanderes-web` and `wanderes-worker`) — the same real key from your local `.env`.
   - `DJANGO_SECRET_KEY` (both `wanderes-web` and `wanderes-worker`) — paste the exact same value you generated in step 2 into both prompts.
5. Apply the Blueprint and wait for both services to build and deploy. `wanderes-web` builds the `production` stage of the `Dockerfile` (leaner than the local dev image — no pytest/ruff, runs under `gunicorn`, not `runserver`); `wanderes-worker` builds the same image but overrides the start command to run the Celery worker instead.
6. Once `wanderes-web` is live, run migrations and load the destination dataset from Render's **Shell** tab (or a one-off job):
   ```bash
   python manage.py migrate
   python manage.py load_destinations
   ```
7. Visit `https://<your-service>.onrender.com/health/` — it should return `{"status": "ok", "database": "ok"}`. `/chat/` should work the same as it does locally.
8. Re-attach the `wanderes.com` custom domain to the new `wanderes-web` service (it was previously pointed at `travelagent-web`) — Render's dashboard, service Settings → Custom Domains. `DJANGO_ALLOWED_HOSTS` is already set to `wanderes.com,www.wanderes.com` in `render.yaml`, so no settings change is needed for this step.
9. Once the new deploy is confirmed healthy, delete the old `travelagent-web`/`travelagent-worker`/`travelagent-db`/`travelagent-redis` resources in the Render dashboard.

