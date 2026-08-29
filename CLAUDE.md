# CLAUDE.md — TravelAgent Working Manual

This file is read automatically at the start of every session in this repository. It captures **how we work together**, decisions already made, and mistakes already made — so they aren't repeated. It is a supplement to `documentation/`, not a replacement for it.

**Read this first, then check current state before doing anything:**
1. [`documentation/PROJECT_STATE.md`](documentation/PROJECT_STATE.md) — exactly where implementation stands right now, including any pending manual actions or pauses.
2. [`documentation/DECISIONS_PENDING.md`](documentation/DECISIONS_PENDING.md) — human decisions currently blocking progress.
3. [`documentation/DEVELOPMENT_LOG.md`](documentation/DEVELOPMENT_LOG.md) — full chronological history of what was built and why.

Do not assume the state described in this file's examples reflects the current phase — always check the three files above first, since they're updated continuously and this file is not.

---

## What TravelAgent is

An Intelligent Travel Consultant — not an AI trip planner, not a travel agency, not a booking platform. Full product/architecture spec lives in `documentation/01`–`15`. Start with `documentation/02_PROJECT_CONTEXT.md` (project philosophy, roles, communication rules) and `documentation/15_IMPLEMENTATION_GUIDE.md` (how development proceeds, phase by phase).

## Non-negotiable working rules

These come directly from `02_PROJECT_CONTEXT.md` and `15_IMPLEMENTATION_GUIDE.md` and have already been reinforced by the user in practice — do not relitigate them:

1. **Never skip development phases. Finish one phase's Definition of Done before starting the next**, even if a technical workaround exists to route around a blocker. If the current phase's DoD requires something that isn't available (e.g., Docker), **pause and say so explicitly** — do not substitute a workaround (e.g., SQLite instead of PostgreSQL) to keep moving, and do not silently skip ahead to a later phase's work just because it happens to be unblocked. Confirmed in practice on 2026-08-28: an initial "this workaround doesn't hurt, let's keep going" judgment call was explicitly overridden by the user in favor of strict phase-by-phase adherence.
2. **Claude Code implements; the human decides.** Never independently decide: AI provider, travel data providers, pricing, monetization, what's Free vs Premium, payment/affiliate providers, privacy/retention policy, recommendation philosophy, or whether a major architectural/technology change is justified. Full list in `15_IMPLEMENTATION_GUIDE.md` §38. When a phase requires one of these, stop and ask — don't guess or default.
3. **Golden rule of scope:** work only on the current approved milestone/task. Don't say "build the whole app" to yourself; implement the next approved step, then stop for review.
4. We communicate in **English** (changed 2026-08-29 — was Portuguese before this date; if resuming an old session transcript, expect Portuguese before this point); all documentation and code comments are in **English**.
5. **The product/UI is English-only for now** (explicit decision, 2026-08-29) — but built translation-ready from day one: `USE_I18N=True`, `LocaleMiddleware`, `LOCALE_PATHS`, and a `LANGUAGES` list already wired in `config/settings/base.py`. Wrap every user-facing string as it's written — `gettext`/`gettext_lazy` in Python, `{% trans %}`/`{% blocktrans %}` in templates — so adding a language later is a translation/config task, not a refactor. Don't add other languages to `LANGUAGES` or build a language switcher until asked.
6. Every meaningful chunk of work gets logged in `documentation/DEVELOPMENT_LOG.md`, and `documentation/PROJECT_STATE.md` gets updated so a future session (or a fresh one after context loss) can resume without re-deriving everything.
7. Be technically critical, not agreeable by default — point out risks and better alternatives per `02_PROJECT_CONTEXT.md`'s "My Role" section.

## Safety judgment calls already made — keep applying these

- **Never try to access, guess, or reset credentials for infrastructure you didn't create.** Found a pre-existing local PostgreSQL 18 Windows service on this machine (unrelated to TravelAgent, likely from another project) — did not attempt to use or modify it without asking the user first.
- **Never modify system/security settings** (BIOS/UEFI, Windows optional features, services) directly — these require the human to act. When encountered (e.g., virtualization disabled, blocking Docker's WSL2 backend), explain exactly what needs to change and how, then wait.
- **Don't introduce architecture-deviating workarounds even when they'd unblock things faster.** E.g., PostgreSQL is the documented source of truth (`04_DATABASE_DESIGN.md`); don't fall back to SQLite locally "just for now" — behavioral differences (JSON fields, constraints, migration behavior) can mask real bugs that only surface later.
- Git commits are only made when the user explicitly asks (per global Claude Code instructions) — infrastructure/config file creation itself doesn't require that permission, but committing does.

## Environment notes specific to this machine

(`C:\Users\vinic\OneDrive\Desktop\TravelAgent`, Windows 11, PowerShell/Git Bash tools)

- Use `py` to invoke Python, not `python` or `python3` (Windows Store alias breaks the latter two). Local venv: `.venv/Scripts/python.exe`.
- Git and a local Python 3.14 (via `py`) are available by default. Docker was **not** pre-installed — it was installed mid-project (2026-08-28) but its engine (WSL2-based) could not start because **hardware virtualization was disabled**. Fix requires: enabling the Windows "Virtual Machine Platform" feature + enabling virtualization (Intel VT-x / AMD-V) in BIOS/UEFI + reboot. See `documentation/PROJECT_STATE.md` for whether this is still pending — check before re-suggesting a Docker install, it may already be done.
- Docker Desktop installed to `C:\Users\vinic\AppData\Local\Programs\DockerDesktop` (user-local, not `Program Files`) — not automatically on `PATH` in already-open shell sessions; use the full path to `resources\bin\docker.exe` or open a fresh terminal.
- A **PostgreSQL 18** server runs as a Windows service (`postgresql-x64-18`) on port 5432, unrelated to TravelAgent's Dockerized Postgres 16. Don't confuse the two; TravelAgent's own Postgres runs inside Docker Compose (`db` service) on the same port, so they cannot run simultaneously without a port conflict — this is expected and fine since TravelAgent uses the Dockerized one.
- Long-running interactive commands (like `docker info` while the engine is still starting) hang past the default tool timeout and get moved to background — check the output file or wait for the task notification rather than assuming failure.

## Technical conventions established (Milestone 1, 2026-08-28)

- Django project lives at the repo root (`manage.py`, `config/`), not nested under `backend/`.
- Settings are split: `config/settings/{base,development,production,test}.py`, loaded via `django-environ` from a local `.env` (never committed — see `.env.example` for the template).
- PostgreSQL via `psycopg` (v3, binary); Redis for cache + Celery broker (`django.core.cache.backends.redis.RedisCache`, built into Django ≥4.0 — no `django-redis` needed).
- Celery is set up but has **no real tasks yet** — infrastructure only, per `15_IMPLEMENTATION_GUIDE.md` Phase 16 ("don't create background jobs until a specific need justifies them").
- Testing: `pytest` + `pytest-django` (not Django's built-in test runner), configured in `pyproject.toml`.
- Linting: `ruff` (replaces flake8+isort+black-style checks in one tool). Settings modules use `per-file-ignores` for `F403`/`F405` since `from .base import *` is intentional there.
- Docker: multi-stage `Dockerfile` (builder installs deps, slim runtime stage); `docker-compose.yml` has `db`, `redis`, `web`, `worker` services.
- CI: GitHub Actions (`.github/workflows/ci.yml`), spins up real Postgres+Redis service containers — this means CI can validate the app end-to-end even when local Docker is unavailable.
- `users`, `travel`, and `trips` domain apps exist as of Phase 4 (2026-08-29). `recommendations`, `ai`, and `integrations` still don't — deliberately deferred until the phases that need them.
- i18n scaffolding is in place (see rule 5 above) even though English is currently the only shipped language — `locale/` directory exists (tracked via `.gitkeep`) for future `.po`/`.mo` catalogs.
- **Custom user model, email-based login** (`AUTH_USER_MODEL = "users.User"`, no username field, `USERNAME_FIELD = "email"`). Google OAuth is a planned future login method but **not implemented** — don't add `django-allauth` or similar until asked. `AUTH_USER_MODEL` cannot change once real migrations exist against a database — don't touch it casually.
- **Trip-related structured data (flights, accommodations) uses real relational models, not JSONField** — `trips.TripFlight` and `trips.TripAccommodation` — specifically so prices stay `DecimalField` (not unvalidated JSON numbers) and connecting flights/multiple stays are just additional rows. Follow this precedent for similar structured, money-bearing, or ratable data rather than reaching for JSONField by default.
- Ruff's `per-file-ignores` in `pyproject.toml` excludes `*/migrations/*.py` from `E501`/`I001` — they're autogenerated, never hand-edited or reformatted.
- **Authentication is Django's built-in session-based auth** (`07_API_DESIGN.md` §3) — no JWT, no separate auth API/DRF token auth. `LoginView`/`LogoutView`/`UserCreationForm` all work with the custom email `USERNAME_FIELD` model with no special-casing needed. Routes live under `/users/` (`users:register`, `users:login`, `users:logout`, `users:account`).

## When resuming a paused/interrupted session

1. Read `documentation/PROJECT_STATE.md` — it has an explicit "current phase" line and, when relevant, a pinned "⚠️ PENDING MANUAL ACTION" or "⏸️ PROJECT PAUSED" section at the top.
2. Don't re-do completed phases. Don't jump ahead of a pause without the user explicitly lifting it.
3. Update all three tracking docs (`PROJECT_STATE.md`, `DEVELOPMENT_LOG.md`, and `DECISIONS_PENDING.md` if relevant) as part of any meaningful change — not just at the end of a session.
