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

Run the test suite:

```bash
docker compose exec web pytest
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
documentation/   Product & architecture docs, development log, decision log
requirements/    Python dependencies (base / development / production)
```

Domain apps (users, traveler profiles, trips, recommendations, AI orchestration, integrations) are introduced in later phases, once the relevant provider and architecture decisions are made — see `documentation/15_IMPLEMENTATION_GUIDE.md`.
