# Project State (resume point)

> Purpose: let Claude (in any future session) resume exactly where the last session left off, without re-reading the entire conversation history. Update this file every time meaningful progress is made or the project pauses. This is the single source of truth for "where did we stop."

**Last updated:** 2026-08-28
**Current phase:** Phase 1 fully validated (DoD complete). Phase 2 (OpenAI) and Phase 3 (curated dataset + Open-Meteo) both decided — adapter implementation and Phase 4 (domain models, Joint Review) are the next steps. No open human decisions blocking progress right now, except supplying the initial curated destination list.

## ✅ RESOLVED — Docker virtualization blocker (2026-08-28)

The user enabled hardware virtualization (BIOS/UEFI) and the "Virtual Machine Platform" Windows feature, then rebooted, as instructed in the previous session. Confirmed working: `docker info` now returns a healthy WSL2-based engine (`Kernel Version: 6.6.114.1-microsoft-standard-WSL2`, Hyper-V requirements satisfied).

**Full Docker Compose validation of Milestone 1 was then run end-to-end and passed:**

1. Created local `.env` from `.env.example` (generated a random `DJANGO_SECRET_KEY`; `.env` is gitignored, not committed).
2. `docker compose up --build -d` — built `web` and `worker` images, started `db` (Postgres 16, healthy), `redis` (7, healthy), `web`, `worker` — all containers came up clean.
3. `docker compose exec web python manage.py migrate` — all built-in Django migrations (admin, auth, contenttypes, sessions) applied without error.
4. `docker compose exec web pytest` — 1 passed (`core/tests/test_health.py`).
5. `curl http://localhost:8000/health/` from the host → `{"status": "ok", "database": "ok"}`, HTTP 200.
6. Celery worker logs confirmed clean startup: connected to `redis://redis:6379/0`, registered `config.celery.debug_task`, `celery@... ready.`
7. Stack was brought down afterward with `docker compose down` (validation run only, nothing needs to stay running).

**Milestone 1's Definition of Done (`14_MVP_IMPLEMENTATION_PLAN.md` §4) is now fully complete.** The project is no longer paused for infrastructure reasons — the remaining blocker is purely the Phase 2/3 human decisions below.

## Where we are

Per `15_IMPLEMENTATION_GUIDE.md`, completed phases:

- [x] Phase 0 — Prepare development environment
- [x] Phase 1 — Project foundation (Django + PostgreSQL + Redis + Docker Compose + Celery skeleton + CI + health check + first test) — **fully validated in Docker, 2026-08-28**

Blocked / not started:

- [x] **Phase 2 — Select AI provider** ✅ Decided 2026-08-28: **OpenAI**, behind the internal AI Provider Abstraction. Assistant persona named **"Lunna"**. See `DECISIONS_PENDING.md` §1 for the full decision record and implementation priorities (conversation context vs. persistent memory, context summarization, relevant-data-only, caching). **Adapter not yet implemented — next actionable step.**
- [x] **Phase 3 — Select travel data providers** ✅ Decided 2026-08-28: **curated static dataset** for destination data (name/country/description/POIs) + **Open-Meteo** for real climate data, both behind the internal Travel Data Interface. Flights/hotels deferred per the MVP plan. See `DECISIONS_PENDING.md` §2. **Adapters not yet implemented; curated destination list not yet supplied — next actionable steps.**
- [ ] Phase 4 — Define initial domain models (Joint Review) — depends on Phase 2 & 3
- [ ] Phase 5 — Authentication
- [ ] Phase 6 onward — see `15_IMPLEMENTATION_GUIDE.md` for the full phase list

## What exists in the repo right now

```
TravelAgent/
├── .github/workflows/ci.yml       CI: lint (ruff) + tests, against real Postgres+Redis
├── config/                        Django project (settings split by environment, urls, wsgi/asgi, celery.py)
├── core/                          Infra-only app: GET /health/ (checks DB connectivity) + test
├── documentation/                 Architecture docs (01–15) + this tracking set
├── requirements/                  base.txt / development.txt / production.txt
├── docker-compose.yml             db (Postgres 16) + redis (7) + web + worker (celery)
├── Dockerfile                     multi-stage (builder installs deps, runtime stays slim)
├── .env.example                   template for local .env (never commit real .env)
├── manage.py, pyproject.toml (ruff+pytest config), .gitignore, .dockerignore, README.md
```

No domain apps exist yet (no `users`, `travel`, `trips`, `recommendations`, `ai`, `integrations`). This is intentional — see `DEVELOPMENT_LOG.md` entry for 2026-08-28.

## Known environment gaps (not decisions — just missing local tooling)

- **Docker Desktop is installed and its engine works** (validated 2026-08-28 — see resolved section above). Virtualization is enabled; WSL2 backend starts cleanly.
- **A PostgreSQL 18 server is also installed and running as a Windows service** (`postgresql-x64-18`, listening on `0.0.0.0:5432`) — pre-existing system state, not created for TravelAgent, unrelated to TravelAgent's Dockerized Postgres 16. Claude Code does not have its credentials and has not touched it. Note: Docker Compose's `db` service also publishes host port 5432 and bound successfully during validation — the two do not appear to conflict in practice (likely because they're not both listening at the same time), but avoid running both simultaneously if port-binding errors ever appear.
- Local Python available via the `py` launcher (3.14). A `.venv` exists at the repo root with dependencies installed; `python manage.py check` and `ruff check .` both pass outside Docker too.
- The Docker image pins Python 3.12 (more predictable wheel availability for `psycopg`) — confirmed working (3.12.14 inside the built image).
- Local `.env` now exists (gitignored) with a generated `DJANGO_SECRET_KEY`, copied from `.env.example`. Future sessions on this machine don't need to recreate it.

## Next action once you unblock Phase 2 & 3

1. Tell Claude Code your AI provider decision and travel data provider decision(s) — see `DECISIONS_PENDING.md` for the specific questions.
2. Claude Code implements the corresponding provider adapters (Phase 2 → AI adapter; Phase 3 → travel data adapters) behind the internal interfaces described in `05_AI_DESIGN.md` §10 and `10_EXTERNAL_INTEGRATIONS.md` §3.
3. Then Phase 4 (initial domain models: User, Traveler Profile, Destination, Trip, Feedback) becomes a **Joint Review** task — Claude Code will propose the Django models based on `04_DATABASE_DESIGN.md`, and you review before they're implemented for real.

## Resume checklist for a fresh Claude session

If you're picking this up cold:

1. Read this file first.
2. Read `DECISIONS_PENDING.md` to see if the human has since made a decision (if so, update this file and proceed to the corresponding phase).
3. Read `DEVELOPMENT_LOG.md` for full historical context on what was built and why.
4. Do **not** re-implement Phase 0/1 — it's done and fully validated in Docker. Do **not** jump ahead to Phase 4+ without confirming Phase 2/3 decisions are actually resolved.
5. If Phase 2/3 are still unresolved, the only useful next step is asking the user for those decisions (see `DECISIONS_PENDING.md`) — do not guess AI/travel-data providers.
