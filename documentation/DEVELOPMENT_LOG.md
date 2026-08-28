# Development Log

This is a human-readable, chronological record of what has actually been built, in what order, and why. It complements (but does not replace) the architecture documents (`01`–`15`). Each entry references the phase/milestone it belongs to, per `15_IMPLEMENTATION_GUIDE.md`.

For a machine-readable snapshot of exactly where implementation currently stands (for resuming work in a new session), see [`PROJECT_STATE.md`](PROJECT_STATE.md). For decisions blocking further progress, see [`DECISIONS_PENDING.md`](DECISIONS_PENDING.md).

---

## 2026-08-28 — Phase 0 & Phase 1: Project Foundation

**Milestone:** Milestone 1 — Project Foundation (`14_MVP_IMPLEMENTATION_PLAN.md`, §4) / Phase 0–1 (`15_IMPLEMENTATION_GUIDE.md`, §4)
**Owner:** Claude Code (infrastructure-only task, no product/architecture decisions required)

### What was done

- Initialized the Git repository (`git init`) at the project root.
- Created the Django project (`config/`) with **split settings** (`base.py`, `development.py`, `production.py`, `test.py`), following `12_DEVELOPMENT_&_DEPLOYMENT.md` §5–6 (environment separation, no hardcoded secrets).
- Configuration is loaded from environment variables via `django-environ`, reading from a local `.env` file (never committed — see `.gitignore`) or from the process environment (used in Docker/CI).
- Created the `core` Django app containing only a `/health/` endpoint that reports application status and PostgreSQL connectivity, per Milestone 1's "basic health check" deliverable. No domain logic lives here — this is deliberately infrastructure-only, since domain models are a **Joint Review** decision (Phase 4) that comes after the AI and travel-data provider decisions.
- Configured **PostgreSQL** as the system of record (`DATABASES`), per `04_DATABASE_DESIGN.md`.
- Configured **Redis** for caching and as the Celery broker (`CACHES`, `CELERY_BROKER_URL`), per `04_DATABASE_DESIGN.md` §7 — never as a persistent data store.
- Added a minimal **Celery** app (`config/celery.py`) with a single `debug_task`, to establish the background-worker infrastructure named in Milestone 1's component list. No real background jobs are implemented yet — per `15_IMPLEMENTATION_GUIDE.md` Phase 16, background jobs are only introduced when a specific need justifies them.
- Wrote a **Docker Compose** environment (`docker-compose.yml`) with four services: `db` (PostgreSQL 16), `redis` (Redis 7), `web` (Django dev server), `worker` (Celery worker) — matching the architecture diagram in `12_DEVELOPMENT_&_DEPLOYMENT.md` §3.
- Wrote a multi-stage `Dockerfile` (build stage installs dependencies; runtime stage stays slim).
- Added `requirements/base.txt`, `requirements/development.txt` (adds `pytest`, `pytest-django`, `ruff`), and `requirements/production.txt`.
- Added a GitHub Actions CI pipeline (`.github/workflows/ci.yml`) that spins up real PostgreSQL and Redis services, installs dependencies, lints with `ruff`, and runs the test suite — matching `12_DEVELOPMENT_&_DEPLOYMENT.md` §10 and `13_TESTING_STRATEGY.md` §14.
- Added a first automated test (`core/tests/test_health.py`) verifying the health endpoint.
- Added `.env.example`, `.gitignore`, `.dockerignore`, and the root `README.md` with setup instructions.

### Implementation decisions made (local, non-architectural — within Claude Code's authority per §39 of `15_IMPLEMENTATION_GUIDE.md`)

- **Django 5.2 LTS** as the target version (long-term support, matches the "designed for long-term evolution" principle in `01_PRODUCT_REQUIREMENTS.md` §8.8).
- **psycopg 3** (binary) as the PostgreSQL driver (actively maintained successor to psycopg2).
- **django-environ** for environment-variable/`.env` parsing.
- **Celery** for background jobs (the standard, well-documented choice for "a simple Django-compatible background task approach" called for in `03_SYSTEM_ARCHITETURE.md` §6.2).
- **pytest + pytest-django** over Django's built-in test runner, for clearer output and fixtures; this does not change how tests are written in a way that affects architecture.
- **ruff** for linting (fast, combines what flake8/isort used to require).
- Project layout keeps `manage.py` and `config/` at the repository root (not nested under a `backend/` folder), matching the `travelagent/` layout sketched in `14_MVP_IMPLEMENTATION_PLAN.md` §4.

### Explicitly NOT done in this phase

- No domain apps (`users`, `travel`, `trips`, `recommendations`, `ai`, `integrations`) were created yet. Per `14_MVP_IMPLEMENTATION_PLAN.md` §4: *"The exact structure should be decided during implementation rather than creating empty applications for every future feature."* Domain models are Phase 4 (Joint Review), which depends on Phase 2 (AI provider selection) and Phase 3 (travel data provider selection) — both explicit **human decisions**.
- No AI provider integration.
- No travel data provider integration.
- No authentication/user system yet (Milestone 2 / Phase 5).

### Verification status

- Local Python (`py`, 3.14) is available; Git is available.
- **Docker Desktop is not installed on this machine** — `docker compose up` could not be run to validate the full environment (Postgres + Redis + Django + Celery) end-to-end. See `DECISIONS_PENDING.md` / `PROJECT_STATE.md` for what this blocks and what was verified instead.
- The GitHub Actions CI pipeline is written and will validate the full stack (via real Postgres/Redis service containers) the first time it runs — but the repository has not yet been pushed to a remote, so CI has not executed yet.

### Why the project stopped here

The next steps in `15_IMPLEMENTATION_GUIDE.md` are **Phase 2 — Select AI provider** and **Phase 3 — Select travel data providers**, both explicitly marked as **Human Decision** (§14 & the "What Claude Code Should Not Decide Alone" list, §38). Per your instructions, the project pauses here until you make/communicate those decisions. See `DECISIONS_PENDING.md` for the specific choices needed and the trade-offs to consider.

---

## 2026-08-28 — Docker Desktop installation attempt

Separately from the Phase 2/3 decisions, we tried to close the "Docker not installed" verification gap noted above.

- User downloaded and ran the Docker Desktop installer. Installed successfully to `C:\Users\vinic\AppData\Local\Programs\DockerDesktop` (a user-local path, not `Program Files` — this is a normal Docker Desktop install mode, just not on `PATH` by default in this shell session; use the full path `...\DockerDesktop\resources\bin\docker.exe` or a fresh terminal).
- The Docker **client** works (`docker version` → v29.7.2).
- The Docker **engine** cannot start: `wsl --status` shows hardware virtualization is disabled on this machine ("O WSL2 não pode ser iniciado porque a virtualização não está habilitada nesta máquina").
- This requires (a) enabling the Windows "Virtual Machine Platform" optional feature and (b) enabling virtualization (Intel VT-x / AMD-V) in BIOS/UEFI firmware, followed by a restart. Both are system-level changes outside Claude Code's authority (see the "Prohibited actions" rule: "Modifying system or security settings"), so Claude Code did not attempt them.
- **User confirmed they will restart to enable virtualization themselves.** This has not happened yet as of this entry. The exact steps and current status are tracked at the top of `PROJECT_STATE.md` under "⚠️ PENDING MANUAL ACTION" so future sessions know not to re-suggest installing Docker (it's installed) and instead check whether virtualization has been enabled.
- This does not block Phase 2/3 decisions or further implementation work — it only blocks the "run `docker compose up` end-to-end" verification step.

---

## 2026-08-28 — Project paused: strict phase adherence requested

The user instructed Claude Code to follow `15_IMPLEMENTATION_GUIDE.md` strictly, phase by phase, until further notice: if a step can't be done, stop until it can; if the next step depends on Docker, pause.

Re-evaluated under that rule: Milestone 1's Definition of Done (`14_MVP_IMPLEMENTATION_PLAN.md` §4) requires validating the environment via `docker compose up`, running migrations, and passing tests inside that environment — none of which has actually happened yet (only partial local checks outside Docker have run). So Milestone 1 is not truly complete, and the next required step depends on Docker, which is currently blocked by the virtualization issue.

**Work is paused.** See the "⏸️ PROJECT PAUSED" note in `PROJECT_STATE.md` for exactly what unblocks it and what to run once Docker's engine is up.

---

## 2026-08-28 — Docker engine unblocked; Milestone 1 DoD fully validated

The user enabled virtualization (BIOS/UEFI + Windows "Virtual Machine Platform") and rebooted, as required to close out the pause above.

- Confirmed `docker info` now reports a healthy WSL2-based engine (`Kernel Version: 6.6.114.1-microsoft-standard-WSL2`; `systeminfo` confirms Hyper-V requirements are satisfied).
- Created local `.env` from `.env.example` (random generated `DJANGO_SECRET_KEY`; file is gitignored, not committed).
- Ran the full Milestone 1 DoD validation end-to-end in Docker:
  - `docker compose up --build -d` — built `web`/`worker` images and started all four services (`db`, `redis`, `web`, `worker`); `db` and `redis` reported healthy.
  - `docker compose exec web python manage.py migrate` — all built-in migrations applied cleanly.
  - `docker compose exec web pytest` — 1 passed.
  - `GET http://localhost:8000/health/` → `{"status": "ok", "database": "ok"}`, HTTP 200.
  - Celery worker log confirmed clean startup and Redis broker connection.
  - `docker compose down` afterward (validation run only; nothing needs to stay running between sessions).
- **Milestone 1's Definition of Done is now fully met.** The project is no longer paused for infrastructure reasons.

### Where this leaves us

The only remaining blocker is the same one noted in the very first Phase 0/1 entry above: **Phase 2 (AI provider) and Phase 3 (travel data providers) are human decisions** (`15_IMPLEMENTATION_GUIDE.md` §38) and have not been made yet. See `DECISIONS_PENDING.md`. No further implementation should proceed past this point until the user provides at least a partial decision on one of them.

---

## 2026-08-28 — Phase 2 decision: AI provider = OpenAI

The user decided: **OpenAI** powers TravelAgent's conversational/reasoning layer. The AI assistant persona is named **"Lunna"** (product naming, not a technical decision).

The user explicitly reinforced several implementation priorities that were already required by `09_AI_ORCHESTRATION.md` but are worth flagging so they aren't under-built when the adapter is implemented:

- Conversation context kept separate from persistent traveler memory (§7).
- Context summarization instead of sending full conversation history every request (§13).
- Only relevant travel data sent to the model — never the whole database or full user history (§4, §11).
- Caching where it makes sense (§13).
- Provider sits behind the internal `AI Provider Abstraction` (§11 / `05_AI_DESIGN.md` §10) so switching providers later doesn't require redesigning the recommendation system.

Full decision record in `DECISIONS_PENDING.md` §1 (now marked resolved). `PROJECT_STATE.md` updated to reflect Phase 2 as decided but **not yet implemented** — the OpenAI adapter itself is the next actionable engineering step once Phase 3 is also resolved (or independently, since the two phases don't block each other).

**Phase 3 (travel data providers) is still an open human decision** — see `DECISIONS_PENDING.md` §2.

---

## 2026-08-28 — Phase 3 decision: destination data = curated dataset, climate = Open-Meteo

The user decided:

- **Destination data** (name, country, description, points of interest): a **curated static dataset** the user will supply/approve, not a live external API for this piece — an explicit, documented MVP simplification.
- **Climate data**: **Open-Meteo**, chosen partly because it's free/keyless and partly because the user explicitly wants it easy to swap later — reinforcing the existing "provider replaceability is an architectural requirement" principle from `10_EXTERNAL_INTEGRATIONS.md` §3.
- **Flights and hotels**: deferred, matching what the MVP plan already allowed.

**Notable discussion during this decision:** the user asked whether the AI itself could just generate destination descriptions instead of using a dataset/API. Pushed back on this using the project's own documented constraint (`05_AI_DESIGN.md` §7 — AI must not invent travel data) plus a provider-swap consistency argument: if destination "facts" came from the model's parametric knowledge, changing AI providers later (an explicit Phase 2 requirement) could silently change what TravelAgent claims about a destination. The user agreed and went with the curated dataset instead.

Full decision record in `DECISIONS_PENDING.md` §2 (now marked resolved). `PROJECT_STATE.md` updated — **all Phase 2/3 human decisions needed to proceed are now made.** Remaining before Phase 4 (domain models, Joint Review) and adapter implementation: the user still needs to supply the initial curated destination list (or ask Claude Code to draft one for approval).
