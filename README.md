# TravelAgent

TravelAgent is an Intelligent Travel Consultant — not an AI trip planner, not a travel agency, not a booking platform. It helps travelers make better, more confident travel decisions through personalized, explainable recommendations.

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
ai/              AI provider adapter (OpenAI), orchestration.py, the Lunna system prompt, and the /chat/ page
recommendations/ Deterministic recommendation scoring/ranking, no models
documentation/   Product & architecture docs, development log, decision log
requirements/    Python dependencies (base / development / production)
```

The AI adapter needs a real `OPENAI_API_KEY` in `.env` to work at runtime (see `.env.example`) — without one it raises a clear configuration error rather than a cryptic SDK failure.

## Try it

Once the stack is running (see above) and `OPENAI_API_KEY` is set, open **http://localhost:8000/chat/** and talk to Lunna.

Load the curated destination dataset (after migrating) with:

```bash
python manage.py load_destinations
```

## Deployment (Render)

Phase 18 (`15_IMPLEMENTATION_GUIDE.md`) needs the app in front of real users, which means it has to be reachable outside `localhost`. [`render.yaml`](render.yaml) is a [Render Blueprint](https://render.com/docs/blueprint-spec) declaring a web service, a Celery background worker, a managed Postgres database, and a managed Key Value (Redis) instance — the same four services `docker-compose.yml` runs locally, deployed for real. It was written against Render's documented spec but has not yet been validated against a live deploy (this repo has no Render account) — if Render's parser rejects anything, report the error back so it can be fixed quickly.

To deploy it:

1. Push this repo to GitHub (already done — `origin` → `wanderes-dev/wanderes`).
2. In the Render dashboard, choose **New > Blueprint** and connect this repository. Render reads `render.yaml` and proposes the four services above.
3. During the Blueprint creation flow, Render prompts for every `sync: false` secret:
   - `OPENAI_API_KEY` (both `travelagent-web` and `travelagent-worker`) — the same real key from your local `.env`.
   - `DJANGO_SECRET_KEY` on `travelagent-worker` — Render auto-generates one for `travelagent-web`; copy that exact generated value into the worker's field too (Render's Blueprint spec has no documented way to share a plain env var value between services automatically — see the comment in `render.yaml`). You can find the generated value afterward under `travelagent-web`'s **Environment** tab in the dashboard.
4. Apply the Blueprint and wait for both services to build and deploy. `travelagent-web` builds the `production` stage of the `Dockerfile` (leaner than the local dev image — no pytest/ruff, runs under `gunicorn`, not `runserver`); `travelagent-worker` builds the same image but overrides the start command to run the Celery worker instead.
5. Once `travelagent-web` is live, run migrations and load the destination dataset from Render's **Shell** tab (or a one-off job):
   ```bash
   python manage.py migrate
   python manage.py load_destinations
   ```
6. Visit `https://<your-service>.onrender.com/health/` — it should return `{"status": "ok", "database": "ok"}`. `/chat/` should work the same as it does locally.
7. Optional: add a custom domain in Render's dashboard, then set `DJANGO_ALLOWED_HOSTS` to that domain (it isn't set in `render.yaml` — `production.py` falls back to Render's own `RENDER_EXTERNAL_HOSTNAME` env var so the first deploy works before a custom domain exists).

