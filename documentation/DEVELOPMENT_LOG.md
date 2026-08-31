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

---

## 2026-08-29 — Initial curated destination dataset drafted and approved

Claude Code drafted an 18-destination list for the curated dataset decided in Phase 3, and the user reviewed/iterated on it over several rounds before approving:

1. First draft: 18 destinations spanning 6 continents, three trip types (beach/city/nature/culture), and three cost tiers, each with name, country, coordinates, short description, and points of interest.
2. User asked to add a "worst season to visit" field alongside the existing "best season," and to make cost-of-living explicit rather than folded into a generic "budget" label.
3. User then asked for a 5-point cost-of-living scale (muito baixo / baixo / médio / alto / muito alto) instead of the initial 3-tier one — Claude Code remapped all 18 destinations to preserve relative ordering while giving a more even spread across the 5 levels.
4. Final version approved as-is.

**Stored at [`documentation/data/curated_destinations.json`](data/curated_destinations.json)** — includes a `$schema_note` explaining it is not yet wired into a Django model (the `Destination` model is a Phase 4 deliverable) and that `best_season`/`worst_season` are descriptive guidance only, not a substitute for the real Open-Meteo climate data the app will query at request time.

`DECISIONS_PENDING.md` §2 and `PROJECT_STATE.md` updated accordingly. **With this, there are no open human decisions blocking progress.** The next steps are: (a) implement the OpenAI and Open-Meteo provider adapters behind their respective internal interfaces, and/or (b) Phase 4 — propose the initial domain models (User, Traveler Profile, Destination, Trip, Feedback) for Joint Review, using this dataset to shape the `Destination` model's fields.

---

## 2026-08-29 — Product decision: English-only UI, built translation-ready; working language switched to English

Two related but distinct decisions from the user:

1. **Product/UI language:** the site is English-only for now. Audited the existing codebase (settings, views, URLs, tests, README, code comments) — everything was already in English, since Phase 1 is infrastructure-only and no user-facing templates/copy exist yet. Nothing needed correcting.
2. **i18n scaffolding, added proactively** so future user-facing strings don't need retrofitting: added `django.middleware.locale.LocaleMiddleware` to `MIDDLEWARE` (positioned after `SessionMiddleware`, before `CommonMiddleware`, per Django's required ordering), added a `LANGUAGES = [("en", "English")]` setting, and `LOCALE_PATHS = [BASE_DIR / "locale"]`. Created an empty `locale/` directory (tracked via `.gitkeep`) for future `.po`/`.mo` catalogs. `LANGUAGE_CODE = "en-us"` and `USE_I18N = True` were already correct from Milestone 1. `python manage.py check` passes with the new settings.
3. **Working convention:** the user asked to communicate in English from now on (previously Portuguese, per `02_PROJECT_CONTEXT.md` and `CLAUDE.md` rule 4). `CLAUDE.md` updated accordingly — rule 4 now reflects English as the working language as of this date, and a new rule 5 documents the English-only-but-translation-ready product decision so it isn't second-guessed or silently changed later (e.g., by defaulting to Portuguese copy, or by adding other languages before asked).

No architecture or scope change beyond this — the convention was that future user-facing strings get wrapped in `gettext`/`gettext_lazy` (Python) or `{% trans %}`/`{% blocktrans %}` (templates) as they're written, not that multi-language support gets built out now.

---

## 2026-08-29 — Phase 4: initial domain models implemented

Proposed a minimal domain model set per `04_DATABASE_DESIGN.md` and `14_MVP_IMPLEMENTATION_PLAN.md` Milestones 2-3, then iterated with the user before implementing:

1. **Login method:** user decided email-based login (not Django's default username), plus a stated intent to add Google OAuth **eventually** — not now. Designed `users.User` as a custom `AbstractUser` subclass with `username = None`, `USERNAME_FIELD = "email"`, and a custom manager (`create_user`/`create_superuser` by email). Google OAuth needs no schema changes now — a library like `django-allauth` would link to this model later without touching it.
2. **Trip data — flight/accommodation:** user initially suggested JSONField for flight and hotel/booking data (flight number, hour, connecting flight, duration, price, price_rate 1-5, rating, company; hotel: address, price, rating, link, website, price_rate) but explicitly invited a better field type if one existed. Recommended proper relational models instead (`trips.TripFlight`, `trips.TripAccommodation`) so prices use `DecimalField` (avoids float-rounding risk on money) and ratings/price_rate are bounded/validated integers instead of unvalidated JSON; connecting flights become additional ordered rows (`leg_order`, `is_connecting`) rather than nested JSON. User agreed.
3. Confirmed "Book" meant accommodation/hotel booking (modeled as `TripAccommodation`), and that flight/accommodation `rating` should use the same 1-10 scale as `trips.Feedback.rating` (not a separate 1-5 scale — `price_rate` stays 1-5, a distinct concept: how the price compares to what's typical).

**Implemented** (per the user's Django organization convention — one app per domain, [[django-project-organization]]):

- `users` app: `User` (custom manager, email login), `TravelerProfile` (deliberately thin — Milestone 2 says not to build the full profile yet).
- `travel` app: `Destination`, shaped to match `documentation/data/curated_destinations.json` field-for-field. Added `travel/management/commands/load_destinations.py` to load/refresh the dataset from that JSON file (maps the dataset's free-form Portuguese `trip_type` strings like "Praia/natureza" onto the model's English choice field).
- `trips` app: `Trip` (FK to Destination via `PROTECT` — a destination shouldn't disappear out from under an existing trip), `TripFlight`, `TripAccommodation`, `Feedback` (DB-level `CheckConstraint` requiring at least a destination or a trip — verified with a test that a bare `Feedback(user=..., rating=...)` raises `IntegrityError`).
- `TripItem` (generic) and community-intelligence entities (`CommunityReview`, `AggregatedInsight`, `TravelerSimilarityData`) are explicitly **not** implemented — deferred to their own later milestones/phases per `04_DATABASE_DESIGN.md`'s "avoid speculative entities" guidance.

**Validation** (per the project's rule to never substitute SQLite for Postgres):

- Because `AUTH_USER_MODEL` can only be set before the first migration touches a database, and the Milestone 1 Docker volume already had the default `auth.User` migrations applied, that volume was dropped and recreated (`docker compose down -v` then `up --build`) — it only held empty smoke-test state, no real data existed in it.
- `makemigrations` → `migrate` ran clean against the fresh Postgres container (users' migration correctly supplies the swappable `auth.User` dependency).
- Added model-level tests (`users/tests/test_models.py`, `travel/tests/test_models.py`, `trips/tests/test_models.py`) — 9 tests total, all passing, run via `docker compose exec web pytest`.
- Fixed a `CheckConstraint.check` → `.condition` deprecation warning (Django 5.1+ rename; no migration needed, same generated SQL).
- `python manage.py load_destinations` loaded all 18 curated destinations successfully.
- `ruff check .` was failing only on autogenerated migration files (long lines, import order) — added `"*/migrations/*.py" = ["E501", "I001"]` to `pyproject.toml`'s per-file-ignores (standard practice; migrations aren't hand-edited) and fixed the small number of genuinely-too-long lines in hand-written code. `ruff check .` now passes clean.
- `docker compose down` afterward — no services need to stay running between sessions.

`PROJECT_STATE.md` updated to mark Phase 4 done. Next: Phase 5 (authentication — email login flows; Google OAuth explicitly deferred) or implementing the OpenAI/Open-Meteo provider adapters.

---

## 2026-08-29 — Phase 5: authentication implemented

Followed the phase order in `15_IMPLEMENTATION_GUIDE.md` (Phase 5 directly follows Phase 4) and `14_MVP_IMPLEMENTATION_PLAN.md` Milestone 2's feature list (registration, login, logout, session management, an authenticated area — explicitly not the full traveler profile yet).

Per `07_API_DESIGN.md` §3, authentication uses **Django's built-in session-based auth, not a separate auth API or JWT** — this was already decided in the architecture docs, not a new call.

**Implemented in the `users` app:**

- `UserRegistrationForm` — a `UserCreationForm` subclass pointed at the custom `User` model with `fields = ("email",)`. Confirmed Django's `UserCreationForm`/`LoginView` work with a custom `USERNAME_FIELD = "email"` model with no extra code — the built-in machinery is already username-field-agnostic.
- `register` view — creates the user, logs them in immediately, redirects to `account`.
- `login`/`logout` — Django's built-in `LoginView`/`LogoutView` wired directly in `urls.py` (no custom views needed).
- `account` — minimal `@login_required` page (Milestone 2 DoD's "authenticated area"): shows email and join date, has a logout button.
- Added `templates/base.html` (minimal shared layout, no styling decisions made — that's a later product/design concern) and `users/templates/users/{login,register,account}.html`.
- Settings: `LOGIN_URL`, `LOGIN_REDIRECT_URL`, `LOGOUT_REDIRECT_URL` pointed at the `users:*` named routes.
- Mounted at `/users/` in the root urlconf, following the established one-app-per-domain convention ([[django-project-organization]]).

**Explicitly not implemented:** Google OAuth (user confirmed this is a "someday" requirement, not needed now — the email-based `User` model design doesn't block adding it later via `django-allauth` or similar). Full traveler profile management (Milestone 2's explicit constraint — that's a later milestone).

**Validation:**

- `makemigrations --check` — no migrations needed (no model changes).
- 7 new tests (registration success/failure, login success/failure, logout, login-required redirect, authenticated access) — 16/16 total passing in Docker.
- `ruff check .` clean.
- Manually exercised the full flow in a real browser against the running Docker container: register → auto-login → account page (showing the registered email) → logout → redirected to login → log back in → account page again. All worked as expected.

`PROJECT_STATE.md` updated to mark Phase 5 done. Next per the phase order: Phase 6 (traveler profile) or Phase 7 (first travel data integration / provider adapters).

---

## 2026-08-29 — Phase 7: first travel data integration (Open-Meteo climate adapter)

The user explicitly asked to do Phase 7 next, ahead of Phase 6 (traveler profile). Noted in `PROJECT_STATE.md` as a deliberate reordering at the user's request, not an accidentally skipped phase — Phase 6 is still outstanding and tracked as such.

Implemented per `10_EXTERNAL_INTEGRATIONS.md` §3 (Integration Layer: `Recommendation System -> Travel Data Interface -> Provider Adapter -> External Provider`) and `14_MVP_IMPLEMENTATION_PLAN.md` Milestone 3's deliverables (provider interface, first adapter, response validation, normalization, timeout handling, basic error handling):

- New `integrations` app — deliberately model-free (no `migrations/`), just Python modules + one `AppConfig` registration, since it holds no persistent data of its own.
- `integrations/climate/base.py` — `ClimateProvider` ABC (the internal Travel Data Interface) and `MonthlyClimateSummary` (the normalized return type), plus `ClimateProviderError`.
- `integrations/climate/open_meteo.py` — `OpenMeteoClimateProvider`, calling Open-Meteo's free, keyless Historical Weather (archive) API for a given month/coordinates. Validates the response shape, normalizes daily arrays into averaged highs/lows/precipitation, wraps network failures and malformed responses in `ClimateProviderError` (never lets raw provider exceptions/response details leak upward, per `07_API_DESIGN.md` §10), and caches results in Redis for 7 days (`10_EXTERNAL_INTEGRATIONS.md` §7 — historical data for a past month doesn't change).
- `integrations/climate/get_climate_provider()` — factory reading `settings.CLIMATE_PROVIDER` (default `"open_meteo"`) so the provider is swappable via settings, not application code (`10_EXTERNAL_INTEGRATIONS.md` §3, "Provider replaceability is an architectural requirement").
- **Documented MVP simplification:** without an explicit `year` argument, the adapter defaults to the most recently completed occurrence of the requested month as a proxy for "typical" conditions, rather than a genuine multi-year climatological average. This keeps the first adapter simple (one HTTP call) while still being grounded in real data rather than invented; averaging across several past years is a natural future refinement once real usage justifies the added complexity/cost, not a current requirement.
- Added `requests` to `requirements/base.txt` (no HTTP client existed yet).

**Validation:**

- 7 new tests, all mocking the HTTP call (`unittest.mock.patch`) so nothing hits the real network during the suite — covers successful averaging, cache-hit behavior, network failure, malformed response, and the provider factory (including an unknown-provider-key error case). Hit one real bug during this: `override_settings(CACHES=...)` with Django's `LocMemCache` persists across tests in the same process (keyed by location, which defaults to a shared value), so the first test's cached result silently satisfied later tests that were supposed to exercise fresh HTTP calls/failures — fixed by clearing the cache in `setUp`.
- All 23 project tests passing (16 previous + 7 new), `ruff check .` clean, no new migrations needed.
- **Also smoke-tested against the real Open-Meteo API** (not mocked) inside the Docker container: `get_climate_provider().get_monthly_climate(latitude=38.72, longitude=-9.14, month=10)` → Lisbon, October 2025, avg high 24.8°C / avg low 17.1°C / 48.6mm precipitation — plausible and consistent with the curated dataset's "best season Mar-Oct" entry for Lisbon. This confirms Milestone 3's Definition of Done for real, not just against mocks.

`PROJECT_STATE.md` updated to mark Phase 7 done and Phase 6 explicitly outstanding. The OpenAI adapter (the other half of the Phase 2/3 provider work) is also still not implemented.

---

## 2026-08-29 — Phase 6: traveler profile edit/retrieve

Closed the gap deliberately left open after Phase 7. Per `14_MVP_IMPLEMENTATION_PLAN.md` Milestone 6, kept the profile itself intentionally minimal ("do not create a large questionnaire unnecessarily... the profile should grow organically") — this reuses the same `TravelerProfile` model defined back in Phase 4 (`preferred_trip_types`, `preferred_cost_of_living`), no new fields added.

**Implemented:**

- `TravelerProfileForm` (`users/forms.py`) — a `ModelForm` overriding `preferred_trip_types` with a `MultipleChoiceField` + `CheckboxSelectMultiple` widget, so editing a JSONField-backed list of tags is a normal checkbox group in the UI rather than a raw JSON textarea.
- `users:profile` view — `@login_required`, `get_or_create`s the caller's own `TravelerProfile` (handles users who registered before this phase existed, or via `createsuperuser`), renders/saves the form, redirects back to itself with a success message on save.
- Authorization is structural, not an explicit permission check: the view only ever reads/writes `request.user`'s own profile — there's no profile-id URL parameter for another user's data to leak through.
- Linked from the account page.

**Note on Milestone 6's full Definition of Done** ("TravelAgent can use authorized profile information to personalize recommendations") - only the edit/retrieve/authorization half exists after this phase. The recommendation engine that would actually consume `preferred_trip_types`/`preferred_cost_of_living` is Phase 8, which hasn't been built yet - expected at this point in the sequence, not a shortfall specific to this phase.

**Validation:**

- 4 new tests: login-required redirect, auto-create-on-first-visit, save persists both fields correctly, and one user's profile edits don't affect another user's profile.
- All 27 project tests passing, `ruff check .` clean, no new migrations.
- Verified live in a browser against the running Docker container: opened the profile form, checked "Beach" and "Culture", selected "Medium" cost tier, saved - got the success message, and confirmed via `manage.py shell` that the database held exactly `['beach', 'culture']` and `3`.

`PROJECT_STATE.md` updated - Phase 6 is done, closing out the "skipped ahead" note from the Phase 7 entry. Next per the phase order: Phase 8 (first recommendation algorithm) - noting the OpenAI adapter (Phase 2's other deliverable) and Milestone 4 (AI Foundation) are still not implemented.

---

## 2026-08-29 — OpenAI adapter implemented (Milestone 4 — AI Foundation)

Closed the other half of Phase 2's deliverable (the AI provider decision itself was made earlier; "Claude implements adapter" was still outstanding). Scoped this strictly to Milestone 4's component list (`14_MVP_IMPLEMENTATION_PLAN.md`): provider interface, adapter, request/response handling, error handling, basic token awareness, travel-only scope prompt - **not** the full orchestrator (context construction from `TravelerProfile`/`Destination`/conversation history, summarization, caching), which is Phase 9's job and would have been scope creep here.

**Implemented**, mirroring the `integrations.climate` pattern for consistency:

- New `ai` app, model-free like `integrations`.
- `ai/provider/base.py` - `AIProvider` ABC (`generate_reply(messages, max_tokens=None) -> AIResponse`), `AIMessage`/`AIResponse` dataclasses, `AIProviderError`. Deliberately doesn't inject a system prompt itself - callers stay in control of exactly what's sent, per `09_AI_ORCHESTRATION.md` §4.
- `ai/provider/openai_provider.py` - `OpenAIProvider`, wrapping OpenAI's Chat Completions API. Validates/normalizes the response (raises `AIProviderError` on SDK errors, missing choices, or empty content), defaults to 600 max output tokens for cost containment (`09_AI_ORCHESTRATION.md` §13), and raises a friendly `ImproperlyConfigured` pointing at `.env.example` if `OPENAI_API_KEY` is blank instead of letting a cryptic SDK auth error surface.
- `ai/provider/__init__.py` - `get_ai_provider()` factory reading `settings.AI_PROVIDER` (default `"openai"`), same settings-driven swap pattern as the climate provider.
- `ai/prompts.py` - `SYSTEM_PROMPT`, encoding the assistant name **"Lunna"** (the Phase 2 decision) plus two already-documented product rules: stay travel-only (`09_AI_ORCHESTRATION.md` §10) and never invent travel data (`05_AI_DESIGN.md` §7). Exists as a constant for the future orchestrator to prepend - not auto-injected by the adapter, keeping it a thin, opinion-free wrapper.
- Settings: `AI_PROVIDER`, `AI_MODEL` (default `gpt-4o-mini`), `OPENAI_API_KEY` (blank by default). Added to `.env.example` with a comment pointing at where to get a key.
- Added `openai` to `requirements/base.txt`.

**Deliberately not real-smoke-tested against the live OpenAI API**, unlike Open-Meteo: a real call costs money on the user's account, and there's no real `OPENAI_API_KEY` configured yet (it's the user's to provide). All 6 new tests mock the OpenAI client via `unittest.mock.patch("ai.provider.openai_provider.OpenAI")`, covering: successful normalization, wrapped SDK errors, empty-content handling, and the missing-API-key config error. Manually confirmed via `manage.py shell` that calling `get_ai_provider()` without a key raises exactly the intended friendly message.

**Validation:** 33/33 tests passing, `ruff check .` clean, no new migrations.

`PROJECT_STATE.md` updated with a clear flag: the adapter is fully built and tested, but **won't work at runtime until the user adds a real `OPENAI_API_KEY` to `.env`.** Next per the phase order: Phase 8 (recommendation algorithm) or Phase 9 (AI orchestration, which will be the first real consumer of this adapter).

---

## 2026-08-29 — Phase 8: first recommendation algorithm

Scoped strictly to `05_AI_DESIGN.md` §2/§5/§6 and `14_MVP_IMPLEMENTATION_PLAN.md` Milestone 5's "Recommendation Logic" diagram (Candidate Destination → Hard Constraints → Basic Score → Ranking). Deliberately **not** in scope: turning a natural-language request like "somewhere warm in October" into numeric constraints (that's Intent & Constraint Extraction, Phase 9's job), and AI-generated explanations of the results (also Phase 9). This phase only covers what happens once the constraints are already explicit numbers.

**Implemented**, in a new model-free `recommendations` app (same style as `integrations`/`ai`):

- `RecommendationRequest` - a dataclass holding already-extracted constraints: `month`, `min_temp_c`/`max_temp_c`, `max_cost_of_living`, `excluded_slugs`, and an optional `user` (for preference/history-aware scoring).
- `generate_recommendations()` - queries all `Destination`s, excludes explicitly-excluded slugs, fetches each candidate's live climate via `integrations.climate.get_climate_provider()` (the Phase 7 adapter - dependency-injectable so tests never touch the network), applies hard constraints (temperature range, cost ceiling), then scores survivors:
  - **Preference fit** (+2): destination's `trip_type` matches something in the user's `TravelerProfile.preferred_trip_types`.
  - **Budget fit**: proportional reward for being under the cost ceiling, not just at it.
  - **Temperature fit**: proportional reward for margin above the minimum requested temperature (capped, so a scorching destination doesn't dominate purely on heat).
  - **Repetition penalty** (-3, soft): the user has a `completed` `Trip` to that destination already - per `05_AI_DESIGN.md` §5, previously-visited destinations should rank lower, not be hard-excluded (unlike `excluded_slugs`, which the caller controls explicitly).
  - A destination the climate provider can't return data for is **skipped, not a hard failure** - graceful degradation per `10_EXTERNAL_INTEGRATIONS.md` §5.
  - Community signals and feedback-based scoring terms from `05_AI_DESIGN.md` §6's fuller formula are **deliberately excluded** - those need aggregation/privacy safeguards that belong to their own later milestones (Feedback & Learning, Community Intelligence), not this first cut.

**Validation:**

- 8 new tests using a small `StubClimateProvider` test double (keyed by rounded lat/lon) injected via `generate_recommendations(..., climate_provider=...)` - covers hard constraints (temperature, cost, exclusions), ranking order, preference-fit scoring, repetition-penalty scoring, graceful degradation when climate data is missing for one candidate, and anonymous-user behavior (no preference/repetition effects without a user). 41/41 total tests passing, `ruff check .` clean, no new migrations.
- **Also validated against real, live data** (not mocked): loaded the 18 curated destinations and called `generate_recommendations(RecommendationRequest(month=10, min_temp_c=20.0, max_cost_of_living=3))` against the real Open-Meteo provider inside Docker. Result was plausible and correctly ranked - Marrakech and Chiang Mai topped the list (cheapest destinations that were also genuinely the warmest in real October 2025 climate data), consistent with Milestone 5's example query ("I want somewhere warm in October, preferably not too expensive").

`PROJECT_STATE.md` updated - Phase 8 done. Next per the phase order: Phase 9 (AI orchestration) - the layer that will turn a real chat message into a `RecommendationRequest`, call `generate_recommendations()`, and use the OpenAI adapter to explain the results in natural language.

---

## 2026-08-29 — Phase 9: AI orchestration

Before starting, checked whether the user had added a real `OPENAI_API_KEY` yet (they were asked, but didn't confirm either way) - confirmed it's still blank, so this phase (like the adapter before it) is validated entirely against mocked/stub providers, no live API calls.

Built `ai.orchestration.get_travel_recommendation(message, user=None)`, a **stateless, single-message** orchestrator implementing `09_AI_ORCHESTRATION.md` §3's pipeline: Intent Understanding → Travel Data + Rules & Constraints → Recommendation Scoring → AI Reasoning. Explicitly does not implement conversation history/persistence or streaming (`09_AI_ORCHESTRATION.md` §7-8) - those need an actual chat UI to exist first (Phase 10), and building them now with nothing to render into would be speculative.

**Extended the AI Provider Abstraction first**, since intent extraction needs reliable structured output: added `AIProvider.generate_structured_reply(messages, json_schema)` as a second abstract method (alongside the existing `generate_reply`) - `05_AI_DESIGN.md` §10 requires this to work for *any* provider, not just be an OpenAI-specific escape hatch, so it went on the interface, not bolted onto the adapter alone. `OpenAIProvider` implements it via the Chat Completions API's `response_format={"type": "json_schema", ...}` (strict mode). Refactored the adapter's internals (`_complete`/`_extract_content`/`_normalize`) so both methods share the request/error-handling path instead of duplicating it.

**The orchestrator itself, in order:**

1. **Intent extraction** (first AI call, structured output): asks the model to extract `is_travel_request`, `needs_clarification`, `clarification_question`, `month`, `min_temp_c`, `max_cost_of_living` from the raw message. Instructed explicitly to never guess a missing month - ask a clarification question instead (`09_AI_ORCHESTRATION.md` §6, "Asking useful clarification questions" is the AI's job). Python-side `_validate_intent()` double-checks the month/cost-tier ranges regardless of what the schema nominally enforced - `09_AI_ORCHESTRATION.md` §9: "AI output should be validated before being treated as trusted application data," schema conformance isn't the same as semantic correctness.
2. **Three short-circuits that skip the (paid) second AI call entirely**: off-topic message → canned `OFF_TOPIC_REPLY`; needs clarification → return the AI's own clarification question directly; no destinations passed hard constraints → canned `NO_MATCHES_REPLY`. This matters for cost (`09_AI_ORCHESTRATION.md` §13) - no reason to spend a second API call explaining zero results.
3. **Scoring**: unchanged, calls straight into Phase 8's `generate_recommendations()`.
4. **Explanation** (second AI call, plain text): prompted with only the top 5 already-ranked candidates (name, country, avg high temp, cost tier, trip type) and an explicit "do not invent any other destinations or facts beyond what is listed" instruction, on top of the `SYSTEM_PROMPT`'s existing anti-hallucination rule. This is where the recommendation's grounding actually gets enforced at the prompt level, not just documented as a principle.
5. **Failure handling**: any `AIProviderError` anywhere in the pipeline is caught once, at the top, and replaced with one generic `FALLBACK_REPLY`. Deliberately simple - no attempt to salvage partial results (e.g., recommendations computed but explanation failed) yet; noted as a reasonable place to revisit if it becomes a real product need.

**Validation:**

- 8 new tests: 2 for `OpenAIProvider.generate_structured_reply` (parses JSON correctly; wraps invalid JSON in `AIProviderError`), 6 for the orchestrator using a small `StubAIProvider` test double (records what it was called with, returns canned structured/text responses) plus the existing `StubClimateProvider` pattern from Phase 8's tests - covering off-topic, clarification, a full valid request, no-matches (asserting the explanation call never happened), an out-of-range month from the AI triggering clarification, and the top-level AI-failure fallback.
- 49/49 total tests passing, `ruff check .` clean, no new migrations (this app has none).

`PROJECT_STATE.md` updated - Phase 9 done, `OPENAI_API_KEY` still flagged as blank. Next per the phase order: Phase 10 (chat interface) - Django templates, message submission, streaming, conversation display - the first thing that lets a person actually talk to Lunna through a browser.

---

## 2026-08-29 — Real OpenAI key added; live validation catches and fixes a real bug

The user provided a real `OPENAI_API_KEY` directly in chat. Flagged that pasting a live secret into a conversation isn't great practice (recommended rotating it once done, since chat text can end up logged in ways `.env` isn't) and added it straight to the local `.env` (which predated the `OPENAI_API_KEY`/`AI_MODEL` lines added to `.env.example` during the adapter phase - `.env` itself needed the same two lines appended). Confirmed `.env` stays gitignored throughout.

**Minimal live call** (`OpenAIProvider.generate_reply` asking for a one-word reply) confirmed the key works: real 200 response from `api.openai.com`, `gpt-4o-mini-2024-07-18`, 14+1 tokens.

**Full live run of the Phase 9 orchestrator** - `get_travel_recommendation("I want somewhere warm in October, not too expensive")` - surfaced a real design bug, not just an interesting edge case: the intent-extraction prompt's "never guess a month, temperature, or budget the user did not state" instruction was *too* conservative. The model correctly refused to invent a specific number for "warm" or "not too expensive," so `min_temp_c`/`max_cost_of_living` both came back `null`. With no hard constraints active, **all 18 destinations passed through untouched and tied at score 0** - the deterministic scoring layer built in Phase 8 never actually engaged, and the second AI call ended up doing real selection work from an unranked, unfiltered candidate list instead of reasoning over already-scored data. Functionally the reply still looked reasonable (the model picked genuinely warm, cheap-looking destinations from the raw data it was shown), but the architecture Milestone 5 calls for - deterministic hard constraints and scoring, AI only explains - wasn't actually happening.

**Fix:** extended `INTENT_EXTRACTION_SYSTEM_PROMPT` with explicit interpretation anchors - "hot" → `min_temp_c=28`, "warm" → `22`, "mild" → `18`; "very cheap/budget" → `max_cost_of_living=2`, "cheap/not too expensive" → `3`, "moderate" → `4` - with an instruction to only leave a field `null` when the user gave no indication *at all* for that dimension, not merely because they used words instead of a number. This is the AI **interpreting the traveler's own words** into an operational threshold the application defines, not inventing a fact about a destination - stays within `05_AI_DESIGN.md` §7's rule rather than violating it.

Re-ran the same live query after the fix: correctly narrowed to 8 destinations (not all 18) with properly differentiated scores; top result matched Phase 8's own pure-scoring test exactly (Marrakech and Chiang Mai, cheapest and genuinely warmest in real climate data). Mocked test suite (49/49) and `ruff check .` both still pass unchanged - this fix is a prompt-text change, not a logic change, so it isn't meaningfully unit-testable; live testing is what caught and confirmed it, and that's an accepted limitation of this kind of change, not a gap to fix with more mocks.

`PROJECT_STATE.md` updated with this finding under the Phase 9 entry. The AI pipeline (adapter + orchestrator) is now validated against real data end-to-end, not just mocks - a meaningfully stronger confidence level than when Phase 9 was first committed.

---

## 2026-08-29 — Phase 10: chat interface (Milestone 5's vertical slice, working end-to-end)

Built the chat UI per `15_IMPLEMENTATION_GUIDE.md` Phase 10's task list (chat interface, message submission, loading state, streaming response, error state, conversation display, basic responsive behavior) and `14_MVP_IMPLEMENTATION_PLAN.md` Milestone 5's flow. Chose to implement real, incremental streaming rather than fake it with a full-response-then-reveal pattern, since both docs name it explicitly and 09_AI_ORCHESTRATION.md §8 describes the progressive pattern in enough detail that it reads as a real requirement, not an optional nicety.

**Extended the orchestrator for streaming first**, since faking streaming with the existing complete-response adapter would have meant redoing this later:

- Added `AIProvider.stream_reply()` to the interface (a third abstract method, alongside `generate_reply`/`generate_structured_reply`) and implemented it in `OpenAIProvider` via the SDK's `stream=True`, yielding `delta.content` chunks. Wrapped both the initial request and the iteration loop in the same `OpenAIError` → `AIProviderError` handling, since a real stream can fail either before the first chunk or mid-stream.
- Rebuilt `ai.orchestration` around `stream_travel_recommendation()` as the actual pipeline (identical intent-extraction/scoring logic to before, but the explanation step now yields incrementally instead of returning a complete string). `get_travel_recommendation()` (the Phase 9 function) is now a thin wrapper that joins the chunks - kept for tests and any caller that genuinely doesn't need incremental output, rather than removed.
- A mid-stream `AIProviderError` yields whatever partial text already arrived, then appends the fallback message as one more chunk - an accepted degrade (partial reply + apology) rather than losing the whole response.
- Updated the existing Phase 9 test doubles (`StubAIProvider`, `FailingAIProvider`) to implement `stream_reply` instead of `generate_reply`, and added dedicated streaming tests (multiple chunks arrive in order, mid-stream failure appends the fallback, short-circuit paths like off-topic/clarification still yield a single canned chunk without touching the network).

**Then the actual view/UI**, in the `ai` app (no new app needed - fits `06_BACKEND_DESIGN.md` §3's "AI: AI orchestration... provider abstraction" module description well enough to also own its own user-facing entry point):

- `GET /chat/` (`ai.views.chat_page`) - renders `ai/templates/ai/chat.html`. Open to anonymous users, per `05_AI_DESIGN.md` §3 ("For unregistered users, recommendations are based on the current conversation... rather than persistent traveler memory") - not gated behind login. If a user IS logged in, `request.user` is passed through so preference-fit/repetition-penalty scoring from Phase 8 kicks in for free.
- `POST /api/v1/recommendations/` (`ai.views.recommendations_stream`) - the exact path already sketched in `07_API_DESIGN.md` §8. Added the pipeline's missing "Request Validation" step here (`09_AI_ORCHESTRATION.md` §3, step 1, never implemented until now): empty or >2000-character messages are rejected with 400 before any AI call is made. Returns a real `StreamingHttpResponse` of just the reply text (`text/plain`) - deliberately does **not** also send the structured `recommendations` list to the frontend in this phase; rendering separate destination cards is a reasonable future enhancement, not something Phase 10's task list asked for, and building a dual-channel (text + structured data) streaming protocol now would have been premature.
- The template: plain HTML + embedded CSS (flexbox column, `100vh` container, mobile breakpoint) + a small vanilla-JS IIFE using `fetch` + `response.body.getReader()` to consume the stream chunk-by-chunk, appending to the DOM as it arrives. Handles network failure and non-2xx responses with a visible error bubble, and disables the input while a request is in flight (loading state). CSRF token read from the `{% csrf_token %}` hidden input and sent as the `X-CSRFToken` header.
- **Explicitly deferred**: true multi-turn conversation memory. Each submitted message is still processed completely independently by the orchestrator (matching `stream_travel_recommendation()`'s stateless design) - the page only keeps a growing visual thread for the current visit; earlier turns are not fed back into the AI's context. This is a real, named limitation, not an oversight - building real conversation threading is separate, larger work for later.

**Validation:**

- 12 new automated tests (3 `stream_reply` cases, 3 streaming-orchestrator cases, 6 view cases mocking `stream_travel_recommendation`) - 61/61 total passing, `ruff check .` clean, no new migrations (this app still has none).
- **Live browser validation**, with the real `OPENAI_API_KEY` now configured: opened `/chat/`, sent "somewhere warm in October, not too expensive" - got the identical Marrakech/Chiang Mai/Hoi An answer already seen in the Phase 9 shell tests, this time streamed incrementally into an actual page. Also live-verified the off-topic guard ("what's the capital of France?" → the canned decline) and the clarification path ("somewhere warm and cheap", no month given → Lunna asked "What month are you planning to travel?") - both worked correctly and both exchanges stayed visible in the on-page thread.
- **Real bug found and fixed via live testing, not unit tests**: `templates/base.html` had no `<meta name="viewport">` tag at all - true since Phase 1, affecting every page, just never visible until testing the chat page on an emulated mobile viewport. Without it, `window.innerHeight` reported 2123 instead of the real 812, so the chat page's `height: 100vh` flex container rendered nearly 3 screens tall with the message input pushed far below the fold - looking, at a glance, like duplicated content. Confirmed via `document.querySelectorAll` that nothing was actually duplicated (one `<h1>`, one `#chat-form`) before concluding it was a viewport-units issue. Fixed by adding the standard `width=device-width, initial-scale=1` tag to `base.html` (benefits every page site-wide); re-tested and `innerHeight` correctly reports 812 with the input properly pinned to the bottom of one screen.

`PROJECT_STATE.md` updated - Phase 10 done, and with it, Milestone 5 ("First Vertical Slice") is functionally complete end-to-end, live-tested, not just unit-tested. Per Milestone 5's own framing ("This milestone is the first major MVP checkpoint"), the natural next step is Phase 11 (First End-to-End MVP, a Joint Review) rather than immediately pushing into further phases.

---

## 2026-08-29 — Phase 11: Joint Review — ran real scenarios, found and fixed a real gap

Phase 11 (`15_IMPLEMENTATION_GUIDE.md`) is explicitly a **Joint Review / Human Decision** checkpoint, not a build phase: "Test: use real scenarios... Human Decision: decide whether the experience is actually good enough to continue expanding." Ran all 7 named scenarios (warm destination, budget destination, romantic destination, beach holiday, city break, family travel, user with strong exclusions) live against the real OpenAI API and real climate data, via `get_travel_recommendation()` directly (same code path the chat view uses).

**Result: 5 of 7 scenarios exposed a real, concrete bug**, not just an expected phase-boundary limitation. "Beach holiday," "city break," "family travel," and "romantic destination" all returned intent extraction with `min_temp_c`/`max_cost_of_living` both `null` (correctly - the AI has no anchor for "romantic" or "beach vacation" as temperature/budget) - but since `RecommendationRequest` had **no `trip_type` field at all**, nothing else filtered either. All 18 destinations passed through tied at score 0 in each case, meaning the second AI call did 100% of the real selection from an unranked, unfiltered list - directly undermining the "deterministic scoring, AI only explains" architecture Milestone 5 calls for.

**Confirmed the exclusion gap conclusively** with a targeted follow-up: asked for "warm in October, not too expensive, do NOT suggest Chiang Mai" - Chiang Mai still appeared in `result.recommendations` at rank #2 (score 1.87). The AI's own free-text reply happened to correctly omit it from the sentence, but the underlying structured data list - what any future feature would actually rely on - still contained it. Root cause: `INTENT_SCHEMA` had no field for exclusions, so there was never a way to populate `RecommendationRequest.excluded_slugs` from a chat message at all.

Reported all of this to the user directly (per `02_PROJECT_CONTEXT.md`'s "be technically critical, not agreeable by default") rather than silently patching it, since Phase 11 explicitly frames "is the experience good enough" as a decision for the user to make. **User's decision: fix trip_type filtering and exclusions now.**

**Fixes implemented:**

- `recommendations.scoring.RecommendationRequest` gained a `trip_type: str | None` field, enforced as a hard constraint (`destination.trip_type != request.trip_type` → excluded) alongside the existing temperature/cost constraints.
- New `travel/services.py` - `find_destination_slugs_by_name(place_names)`, matching a list of free-text names against `Destination.name`/`Destination.country` (case-insensitive substring), returning matching slugs. Placed in the `travel` app since "Destination search" is explicitly that app's named responsibility per `06_BACKEND_DESIGN.md` §3.
- `ai.orchestration.INTENT_SCHEMA` gained two fields: `trip_type` (enum: `beach`/`city`/`nature`/`culture`/`null`) and `excluded_place_names` (array of strings). The extraction prompt explicitly instructs the model **not** to force-fit "romantic" or "family-friendly" into one of the four trip_type categories just because it has to pick something - leave it `null` rather than guess. `_validate_intent()` defensively re-checks both (unknown trip_type values reset to `null`; non-string/empty items dropped from the exclusion list), matching the existing "never fully trust the schema" pattern.
- `stream_travel_recommendation()` now resolves `excluded_place_names` through `find_destination_slugs_by_name()` before building the `RecommendationRequest` - the first time `excluded_slugs` has ever been reachable from an actual chat message, not just direct Python calls.

**Validation:**

- 10 new tests: a `trip_type` hard-constraint test in `recommendations`, six unit tests for `find_destination_slugs_by_name` (name match, country match, case-insensitivity, no-match, empty-input, multi-term), and three orchestrator-level tests (trip_type filters correctly end-to-end, exclusion-by-name removes the right destination, exclusion-by-country removes multiple). 71/71 total tests passing, `ruff check .` clean, no new migrations.
- **Re-verified live** (real OpenAI + real climate data) after the fix: "beach vacation in July" now correctly narrows to 3/18 beach-only destinations (Dubrovnik, Santorini, Maldivas); "city break in March" narrows to 5/18 city-only destinations; the Chiang Mai exclusion test now shows it genuinely absent from `result.recommendations` (7 destinations, not 8) - confirmed at the data level this time, not a coincidence of the AI's phrasing.

**Explicitly still open, not fixed, not asked for:** "romantic" and "family-friendly" have no representation in the data model at all - trip_type's four categories don't cover them, and inventing new categories or traveler-composition attributes is a genuine product-shape decision, not something to wire up unilaterally alongside this fix. Also still open: a couple of AI replies during testing added facts not present in our dataset (nearby beach towns near Lisbon, general safety claims about Kyoto) - a grounding concern flagged but not addressed in this pass.

`PROJECT_STATE.md` updated. **Phase 11's actual "Human Decision" - whether the experience is good enough to continue expanding - has not been explicitly made yet**; only two specific bugs surfaced by the review have been fixed so far.

---

## 2026-08-29 — Recommendation philosophy decided: unplanned requests fall to AI judgment, logged for review

Asked the user directly (in Portuguese, at their request, "just this once") whether "romantic"/"family-friendly" needed data-model representation, since that's a recommendation-philosophy call explicitly reserved for the human per `CLAUDE.md` rule 2.

**Decision:** imagine a real user - they'll ask for things this system can't predict in advance. When a request doesn't match anything the deterministic model covers, the AI should answer from its own general knowledge rather than the app trying to enumerate every possible category ahead of time. The system should either learn to answer these well, or **register/log** that it couldn't confidently decide, so real usage - not guesswork - eventually informs what's worth formalizing.

This resolves the open Phase 11 question without adding new `Destination` categories or a "traveler composition" concept - which would have been guessing at product shape without evidence. It also matches a principle already stated elsewhere in the docs (`14_MVP_IMPLEMENTATION_PLAN.md` Milestone 6: "the profile should grow organically as the product learns what information actually improves recommendations") - just applied to recommendation dimensions generally, not only to `TravelerProfile`.

**Implemented as structured logging**, not a new database model - persisting an "unhandled request" table would be premature before any real analytics need exists (`15_IMPLEMENTATION_GUIDE.md`'s general philosophy: don't build ahead of demonstrated need; Phase 17, Product Analytics, is explicitly later). Added a `logging.getLogger(__name__)` logger to `ai/orchestration.py` with three log points:

- **INFO** when a valid travel request extracts no deterministic constraints at all (`trip_type`, `min_temp_c`, `max_cost_of_living` all `null`) - "relying on AI judgment," with the message and month for context.
- **INFO** when hard constraints eliminate every candidate (no matches) - includes the full extracted constraint set, useful for spotting constraints that are too strict or a dataset gap.
- **WARNING** when `AIProviderError` occurs, whether during intent extraction or mid-stream during the explanation - a genuine technical failure, distinct from the two philosophy-driven INFO cases above.

**Validation:**

- 3 new tests using Django's `assertLogs()` context manager, asserting the right log level and message substring for each of the three cases. 74/74 total tests passing, `ruff check .` clean, no new migrations.
- **Confirmed live**: called `get_travel_recommendation("We want a romantic getaway in June")` against the real OpenAI API - console output showed exactly `No deterministic constraints extracted - relying on AI judgment. message='We want a romantic getaway in June' month=6`, immediately before the (real, working) AI-reasoned reply.

`PROJECT_STATE.md` updated with Claude Code's assessment that this satisfies Phase 11's checkpoint - but noted explicitly that the user has not yet said "continue expanding" in so many words, so that should be confirmed rather than assumed before treating Phase 12+ as greenlit.

**User confirmed explicitly: "yes u can follow."** Phase 11 marked closed in `PROJECT_STATE.md`.

---

## 2026-08-29 — Phase 12: Travel History

Per `15_IMPLEMENTATION_GUIDE.md` Phase 12 (record visited destinations, associate with users, allow correction, use history in recommendations) and `14_MVP_IMPLEMENTATION_PLAN.md` Milestone 7. `04_DATABASE_DESIGN.md` §2/§4 lists "Travel History" and "Trip" as separate entities under `User`, not the same thing - a Trip is a planned/completed experience with its own items (flights, accommodations, Phase 4); Travel History is meant to be much simpler, a standalone "I've been to X, roughly year Y" record that doesn't require ever creating a full Trip.

Worth noting: the repetition-penalty logic added back in Phase 8 (`recommendations.scoring._visited_destination_slugs()`) already looked at `Trip.objects.filter(status="completed")` - but there has never been a Trip-creation UI (that's Phase 13, not built yet), so that code path was real but practically unreachable by any actual user until this phase gave a second, simpler way to record "I've been here."

**Implemented:**

- `trips.TravelHistoryEntry` - `user` FK, `destination` FK, `visited_year` (nullable `PositiveSmallIntegerField` - "approximate travel dates where useful," not a full date).
- Full CRUD in the `trips` app (its first views/urls/templates): `/trips/history/` (list), `/history/add/`, `/history/<pk>/edit/`, `/history/<pk>/delete/` (confirmation page, POST to actually delete). All `login_required`; authorization is structural - every view fetches via `get_object_or_404(TravelHistoryEntry, pk=pk, user=request.user)`, so another user's entry 404s rather than leaking or being editable, matching the pattern already established for `users:profile`.
- `recommendations.scoring._visited_destination_slugs()` updated to union completed `Trip` destinations **and** `TravelHistoryEntry` destinations - either is sufficient to trigger the existing soft repetition penalty. No change to the penalty mechanic itself (still a score subtraction, not a hard exclusion) - `05_AI_DESIGN.md` §5 and this phase's own "important rule" both say previously-visited destinations should be deprioritized, not banned, and that was already correctly implemented.
- Linked from the account page ("My travel history").
- Registered in Django admin.

**Validation:**

- 10 new tests: a model `__str__` test, and 7 view tests covering the full CRUD flow plus authorization (list only shows own entries, cannot edit/delete another user's entry - both 404), plus one `recommendations.scoring` test confirming a `TravelHistoryEntry` alone (no Trip) triggers the same penalty. 83/83 total tests passing, `ruff check .` clean. One new migration, `trips.0003_travelhistoryentry`.
- **Live-verified the actual effect on scoring, not just the CRUD UI**: added "Chiang Mai, 2019" through the real browser for a real logged-in user (`browsertest@example.com`, left over from earlier Phase 6 testing), then called `get_travel_recommendation(..., user=that_user)` against the real OpenAI + Open-Meteo APIs. Chiang Mai's `repetition_penalty` came back `3.0` and it dropped from top-ranked (as seen in earlier Phase 8/11 live tests with no history) down to 5th place - still present in the results, just deprioritized, exactly matching the intended behavior.

`PROJECT_STATE.md` updated - Phase 12 done. Next per the phase order: Phase 13 (Trip Management) - create/edit/view/delete a real `Trip`, which will finally make the completed-Trip repetition-penalty path reachable by real users too, not just Travel History entries.

---

## 2026-08-29 — Repository pushed to GitHub (wanderes-dev/wanderes)

User asked to push the project to `https://github.com/wanderes-dev/wanderes.git`. First attempt failed with "Repository not found" even though Windows Git Credential Manager had a cached credential - turned out GCM was authenticating as `cantarino10`, an account without access to that repo. User confirmed it should be a different account. Rejected the `cantarino10` credential (`git credential reject`), which revealed GCM had a *second* cached credential for github.com under `wanderes-dev` - the correct account. Re-ran the push and it succeeded (`master` → `origin/master`, tracking set up). Did not enter any password/token on the user's behalf at any point - only removed a stale cached credential so GCM would offer the already-cached correct one instead.

Confirmed `.env` was never staged or pushed (gitignored from the start, per Milestone 1's setup).

---

## 2026-08-29 — Phase 13: Trip Management

Per `15_IMPLEMENTATION_GUIDE.md` Phase 13 / `14_MVP_IMPLEMENTATION_PLAN.md` Milestone 8: create/edit/view/delete a `Trip`, add destination/dates, and "save relevant recommendations." Explicitly not building advanced itinerary management - no new Trip Item types, no complex planning tools.

**Trip CRUD:**

- Added `Trip.name` (blank-able nickname field, e.g. "Summer in Lisbon") - Milestone 8 explicitly lists "Name a trip" as a feature the existing `Trip` model (Phase 4) didn't have. Migration `trips.0004_trip_name`.
- `TripForm` (`name`, `destination`, `start_date`, `end_date`, `status`), with HTML5 date inputs for the date fields.
- Views: `trip_list`, `trip_create`, `trip_detail`, `trip_edit`, `trip_delete` - all `login_required`, all structurally scoped to `user=request.user` (`get_object_or_404(Trip, pk=pk, user=request.user)`), matching the authorization pattern already established for `TravelHistoryEntry` and `users:profile`. Delete has a confirmation page, matching the Travel History delete flow.
- Linked from the account page ("My trips").

**"Save relevant recommendations" - implemented for real, not deferred as a stretch goal:**

Phase 10's chat page deliberately didn't expose structured destination data to the frontend (documented then as "a reasonable future enhancement"). This phase is that enhancement. Rather than adding a second endpoint or server-side session state to remember "what was just recommended," the streaming response itself now carries both pieces of information in one request:

- `ai/views.py`'s `recommendations_stream` appends a distinctive delimiter (`\n<<<TRAVELAGENT_RECOMMENDATIONS>>>\n`) followed by a JSON array of `{slug, name, country}` for the recommended destinations, after the visible reply text finishes streaming.
- The chat page's JS now buffers the incoming stream into a string (rather than appending each chunk directly to the bubble), checks for the delimiter on every read, and only ever displays the portion before it - so the bubble never shows the raw footer even momentarily. Once the stream ends, whatever comes after the delimiter is parsed as JSON and rendered as a list of "Save `<name>` as a trip" links, each pointing at `/trips/create/?destination=<slug>`.
- `trip_create`'s view reads that `?destination=` query parameter and pre-selects it in the form via `initial=`.

This keeps the "AI Provider Abstraction" and orchestration layers completely untouched - the extra data was already sitting in `StreamingOrchestrationResult.recommendations`, computed synchronously before the text stream even starts; this only changes how the view packages the response and how the page renders it.

**Validation:**

- 16 new tests: full Trip CRUD + authorization (list/detail/edit/delete all scope-checked the same way as Travel History's), the destination-prefill-from-query-param behavior, and a `recommendations_stream` test confirming the footer is present/absent/well-formed. Hit one test bug (not a code bug): hardcoded `value="1"` assuming a fresh auto-increment sequence - Postgres doesn't reset `SERIAL` counters between rolled-back test transactions, so the real PK was 77. Fixed by asserting against `self.destination.pk` instead of a literal. 93/93 total tests passing, `ruff check .` clean.
- **Full real, live end-to-end verification**, not just the CRUD pages in isolation: asked Lunna a real question in the browser ("somewhere warm in October, not too expensive"), got a real streamed reply plus 5 clean "Save as trip" links (no leaked delimiter/JSON in the visible text), clicked "Save Marrakech as a trip," confirmed the create form opened with Marrakech pre-selected, saved it as "October trip," landed on its detail page, and confirmed it appears in the trip list. The whole chat → recommend → save → view loop works for real.

`PROJECT_STATE.md` updated - Phase 13 done. Next per the phase order: Phase 14 (Feedback).

---

## 2026-08-29 — Phase 14: Feedback

Per `15_IMPLEMENTATION_GUIDE.md` Phase 14 - the Feedback half of Milestone 9 only; "Learning From Feedback" (using it to actually influence recommendation scoring) is Phase 15, a separate Joint Review phase, deliberately not touched here.

The guide explicitly flags one thing as a **Human Decision**: "Define the initial feedback taxonomy. Keep it small." Rather than invent tags unilaterally, proposed a small candidate set (4 positive, 4 negative - matching the doc's own example, "Too crowded" / "Excellent food") and got explicit approval before writing any code.

**Approved taxonomy** (`trips.FEEDBACK_TAG_CHOICES`): Excellent food, Great value, Friendly locals, Beautiful scenery, Too crowded, Overpriced, Poor weather, Hard to get around. Kept as a plain Python constant rather than a DB `choices=` constraint, since `Feedback.tags` is a JSONField list (already existed from Phase 4) - `FeedbackForm` is what actually restricts the UI to these values, via `CheckboxSelectMultiple`.

**Implemented:**

- `FeedbackForm` (`rating`, `tags`, `comment`) - `rating`'s existing model-level validators (1-10, from Phase 4) are picked up automatically by the ModelForm, satisfying the phase's "Validation" requirement without extra code.
- `trip_feedback` view at `/trips/<pk>/feedback/`: looks up any existing `Feedback` for `(trip, user)` and uses it as the form's `instance` if found - so resubmitting the form **edits** the existing entry instead of creating a duplicate. No hard DB unique constraint added for this (a `(user, trip)` uniqueness constraint would also have been reasonable, but the get-or-build-in-the-view approach needed no migration and is simple enough for this scale). Structurally scoped to `user=request.user`, matching every other trip view.
- Trip detail page now shows existing feedback - rating, comment, and tag labels translated from the stored keys (`excellent_food`) to their human-readable form (`Excellent food`) via a small dict built from `FEEDBACK_TAG_CHOICES` in the view - with an "Edit feedback" link, or "Leave feedback" if none exists yet.

**Validation:**

- 6 new tests: create with rating/tags/comment, reject an out-of-range rating (11), resubmission updates rather than duplicating, cross-user access 404s, and the tag-label translation actually shows "Excellent food" rather than the raw `excellent_food` key. 99/99 total tests passing, `ruff check .` clean, no new migrations (the model didn't change).
- **Verified live**: used the trip saved during Phase 13's live test ("October trip" → Marrakech), opened its feedback form, checked "Excellent food" and "Too crowded," rated it 8/10, added a comment, and saved - the trip detail page immediately showed "Rating: 8/10," "Tags: Excellent food, Too crowded" (correct labels, not keys), and the comment text.

`PROJECT_STATE.md` updated - Phase 14 done. Next per the phase order: Phase 15 (Learning From Feedback) - a Joint Review phase to decide how this feedback should actually influence future recommendation scoring, not something to design unilaterally given `05_AI_DESIGN.md` §8's note that "disliking one destination does not necessarily mean the user dislikes every destination with similar characteristics."

---

## 2026-08-29 — Conversational feedback, travel history, and future-intent capture

User request, direct and out-of-sequence relative to the guide's numbered phases: feedback should be givable straight through the chat - "no need to go to another page to do it" - and the AI should register a past visit or a stated future travel intention from the conversation itself, not only through the dedicated forms built in Phases 12-14.

This is a delivery-channel extension of Phases 12/13/14's existing models (`TravelHistoryEntry`, `Trip`, `Feedback`), not Phase 15 ("Learning From Feedback" - using feedback to influence recommendation scoring, still untouched).

**Design decision: one classification call, not a separate one.** Every chat message already went through a single AI call (`_extract_intent`) to determine recommendation constraints. Rather than adding a whole extra "classify this message" call ahead of it (which would have added cost/latency to the most common path, recommendation requests, for the sake of the less common ones), the existing extraction schema was widened to also classify `message_type` into `recommendation` / `feedback` / `future_intent` / `off_topic` in the same call, with type-specific fields alongside the existing recommendation fields (all still required by OpenAI's strict structured-output mode, populated only for the matching type). `is_travel_request` (a boolean) was replaced by the more general `message_type` enum - a breaking change to the schema's shape, so every existing test's `_intent()` factory and the two hardcoded `is_travel_request=False` call sites needed updating (straightforward, no logic changes).

**Feedback via chat:**

- Extracts `feedback_destination_name`, an optional `feedback_rating` (1-10, explicitly instructed to never invent one from a neutral factual statement), `feedback_tags` (constrained to the same 8-tag taxonomy approved in Phase 14), and `feedback_comment`.
- Resolves the destination name through the existing `travel.services.find_destination_slugs_by_name()` (the same helper Phase 11's exclusion fix uses) - no new resolution logic needed.
- **Giving feedback always registers a `TravelHistoryEntry` too** (`get_or_create`) - directly answers "the AI must... register a travel that occurred by user": you can't credibly rate a place you haven't been.
- If no rating was expressed, only the history entry is created - `Feedback.rating` is a required field, so a half-formed Feedback row was never an option; the acknowledgment gently invites a rating instead of silently dropping the mention.
- Feedback persists via `update_or_create` keyed on `(user, destination, trip=None)` - repeating/correcting feedback in a later message updates the same record. This is deliberately independent from trip-specific feedback given through `/trips/<pk>/feedback/` (which is keyed by an actual `trip`, not `None`) - a user can have both a general destination opinion and a trip-specific one; this phase didn't attempt to merge or reconcile the two.

**Future travel intent via chat:**

- Extracts `future_destination_name`, resolves it the same way, and creates a `Trip` with `status="planned"` via `get_or_create` (so stating the same intent twice doesn't create duplicate trips) with an auto-generated name (`"Someday: {destination}"`).

**Shared handling for both new paths:**

- Anonymous users get `NEEDS_LOGIN_REPLY` - there's no account to attach a history entry, feedback, or trip to. Recommendations remain available to anonymous users as before (unchanged).
- An unrecognized destination name (not in the curated 18-destination dataset) degrades gracefully: acknowledges the message without crashing or persisting a broken/missing reference, and logs it at INFO level - the same "log what fell outside the deterministic model" pattern established in Phase 11's recommendation-philosophy decision, now applied to catalog gaps too.
- Acknowledgment replies are templated strings, not a second AI call - these are simple confirmations, and adding a paid API call just to phrase "thanks, noted" more elaborately isn't worth it given the project's consistent cost-consciousness (`09_AI_ORCHESTRATION.md` §13).

**Validation:**

- 8 new tests covering: feedback with a rating (creates both `Feedback` and `TravelHistoryEntry`), feedback without a rating (history only), resubmission updates rather than duplicates, both new paths correctly gate anonymous users, future-intent creates a planned `Trip`, and an unrecognized destination name doesn't crash. Also fixed a test-authoring bug along the way: three assertions checked for `"Lisbon"` (capitalized) against a test fixture destination whose `name` field was actually the lowercase `slug` value (`"lisbon"`) - fixed the assertions, not the shared fixture helper other tests rely on.
- 106/106 total tests passing, `ruff check .` clean, no new migrations (every model involved already existed).
- **Verified live in one continuous real conversation** against the actual OpenAI API: "I went to Marrakech last month, it was amazing! Great food but way too crowded, I'd give it a 9/10" → correctly classified as feedback, created a real `Feedback` row (rating 9, tags `['excellent_food', 'too_crowded']`) and a `TravelHistoryEntry`, both confirmed via shell. "I want to visit Bali someday" → correctly classified as future intent, created a real `Trip` (status `planned`, name `"Someday: Bali"`), confirmed via shell. Then, in the same conversation, "somewhere warm and cheap in December" → the original recommendation flow still worked exactly as before, including Phase 13's "Save as trip" links - confirming no regression from widening the schema.

`PROJECT_STATE.md` updated. This does not change what Phase 15 (Learning From Feedback) still needs to do - feedback collected this way, like feedback collected through the standalone form, does not yet influence recommendation scoring.

---

## 2026-08-29 — Phase 15: Learning From Feedback (and a real test-infrastructure bug found along the way)

Per `15_IMPLEMENTATION_GUIDE.md` Phase 15 (Joint Review), explicitly flagged as a **Human Decision**: "Define what information may automatically change a user's profile. Not every piece of feedback should permanently change preferences." Proposed a specific, conservative rule set and got approval (including an explicitly-accepted edge case) before writing any code - same pattern as Phase 14's tag taxonomy.

**Approved rules:**

- Runs as a background Celery task, triggered by a `post_save` signal on `Feedback` - matches the flow diagram (`Feedback → Persist → Background Processing → Update Preferences`) and means the user never waits for it during the request/response cycle.
- **Recomputes from *all* of a user's feedback on every run**, rather than incrementing stored counters - this single design choice is what makes the task retry-safe and duplicate-processing-safe (both explicit review criteria): running it twice, out of order, or after a retry produces the identical result, since it's not accumulating state incrementally.
- `preferred_trip_types`: additive only, added once a trip type has ≥2 ratings of 8+. Never removes a type - not one the user set manually, not one a previous run added.
- `preferred_cost_of_living`: only auto-set if the user hasn't already set it themselves - an explicit choice always wins over an inferred one. Same ≥2-ratings-of-8+ threshold for a cost tier.
- Accepted edge case (confirmed explicitly): if a user manually removes a trip type from their profile but keeps rating that type of destination highly, a later recompute can add it right back, since the task has no memory of a deliberate removal - "keep it small" won over building that tracking.

**Implemented:**

- `trips/tasks.py` - `update_traveler_preferences_from_feedback(user_id)`, a `@shared_task`. This is the **first real Celery task in the project** - the infrastructure has existed since Milestone 1 with deliberately zero tasks, per `15_IMPLEMENTATION_GUIDE.md` Phase 16's "don't create background jobs until a specific need justifies them." This phase is that need.
- `trips/signals.py` - a `post_save` receiver on `Feedback` that calls `.delay()`. Connected via `TripsConfig.ready()` (standard Django pattern for wiring up signals without import-order issues).

**A real, previously-invisible bug surfaced during testing**: the first test relying on the signal-triggered task kept failing - the task's own logic, when called directly as a plain function, worked correctly and created the expected `TravelerProfile`, but the exact same call *through* `.delay()` (as the signal actually invokes it) silently did nothing. Spent real effort tracing this because it looked exactly like a subtle Celery eager-mode/database-visibility problem. The actual root cause turned out to be much simpler and unrelated to this feature's logic at all: **`docker compose exec web pytest` has been silently running the entire test suite under `config.settings.development` instead of `config.settings.test` since Milestone 1.** `docker-compose.yml` sets `DJANGO_SETTINGS_MODULE: config.settings.development` as an environment variable for the `web`/`worker` services (needed so `manage.py runserver`/`celery worker` behave correctly when the stack is run normally) - and pytest-django gives an *existing* environment variable priority over `pyproject.toml`'s `[tool.pytest.ini_options] DJANGO_SETTINGS_MODULE` setting. Confirmed directly: `django: ..., settings: config.settings.development (from env)` appeared in every prior test run's output all along, easy to miss since it's normal pytest-django banner text, not a warning.

This had been completely harmless for 14 phases' worth of tests, because nothing before this depended on a setting that actually differs between `development.py` and `test.py` in a way that changes behavior - `CELERY_TASK_ALWAYS_EAGER` is the first one that does (`True` in `test.py`, `False` under `development.py`'s inherited default). Confirmed **CI was never affected**: `.github/workflows/ci.yml` already sets `DJANGO_SETTINGS_MODULE: config.settings.test` as an explicit job-level environment variable, which is exactly the same mechanism that was masking the problem locally, just pointed at the right module.

**Fix**: run local Dockerized tests with an explicit override: `docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test web pytest`. Documented this in `CLAUDE.md` so future sessions don't need to rediscover it. Also added `CELERY_TASK_EAGER_PROPAGATES = True` to `config/settings/test.py` - without it, an exception raised inside a task called via `.delay()` in eager mode is silently swallowed into the (never-inspected) `EagerResult` instead of failing the test loudly; this would have hidden a *real* bug just as easily as it hid this environment issue, so it's a good permanent addition regardless of what caused this specific investigation. (A `conftest.py` fixture that tried to force `celery_app.conf.task_always_eager = True` directly was attempted first, on the mistaken assumption that Celery's `app.conf` was stale/cached - it wasn't; that fixture didn't fix anything and was removed once the real cause was found.)

**Validation:**

- 9 new tests: trip-type additive logic (adds after 2 high ratings, doesn't add after 1, doesn't add on low ratings), never removes an existing trip type, cost-of-living set-when-unset and not-overridden-when-already-set, idempotent recompute (running twice produces the same result), no-feedback no-op, and the signal itself actually firing end-to-end. 115/115 total tests passing (once run under the correct settings module - some tests were silently running under the wrong one before, though harmlessly), `ruff check .` clean, no new migrations (no new models).
- **Verified against the real Celery worker**, not eager mode: created real `Feedback` via `manage.py shell` (not a test), confirmed via `docker compose logs worker` that the task was received and processed by the actual separate worker process, then confirmed the real `TravelerProfile` was updated exactly as the approved rules specify - `preferred_trip_types` gained `beach` after two 9/10 ratings on beach destinations, while `preferred_cost_of_living` correctly stayed at its existing value (`3`, set manually back during Phase 6's live testing) rather than being overwritten by the new signal, even though the new destinations' cost tier would otherwise have qualified.

`PROJECT_STATE.md` updated - Phase 15 done, all 15 numbered phases from `15_IMPLEMENTATION_GUIDE.md` now complete. The test-settings tooling note is recorded in `CLAUDE.md` for future sessions.

---

## 2026-08-30 — Post-Phase-15 revision (code + infrastructure review)

**Milestone:** Not a numbered guide phase - a user-requested full review pass across all 15 completed phases before starting Phase 16, to catch anything that had slipped through 15 phases of forward momentum.

**What was reviewed:** full Docker-based validation (migrations, 115/115 tests under `config.settings.test`, `ruff check .`, `manage.py check --deploy`), plus a manual critical-read pass over settings (`base.py`/`production.py`/`test.py`), the AI orchestration/provider layer, every view's authorization pattern, the recommendation scoring module, the Phase 15 Celery task, and the Docker/CI configuration.

**Two real, previously-unnoticed issues found and fixed:**

1. **CI never actually ran on push.** `.github/workflows/ci.yml`'s `push:` trigger was scoped to `branches: [main]`, but this repo's only branch has always been `master` (confirmed via `git branch -a` - no `main` ever existed here). Every push made across this entire session silently did not trigger CI - the "tests + lint validate every push" safety net assumed throughout the project log did not actually exist for direct pushes, only for pull requests (of which there have been none). **Fixed**: changed the trigger to `branches: [master]`.
2. **Production settings had no fail-fast guard for a missing `SECRET_KEY`.** `production.py` already raised `RuntimeError` if `ALLOWED_HOSTS` was unset, but had no equivalent check for `SECRET_KEY` - if `DJANGO_SECRET_KEY` were ever missing in a real deployment, it would have silently fallen back to `base.py`'s hardcoded insecure default string instead of failing loudly. **Fixed** by adding the same fail-fast pattern. **Caught a bug in the fix itself during verification**: the first version only checked `SECRET_KEY == "unsafe-development-key-change-me"`, but `django-environ` doesn't fall back to that default when the env var is explicitly set to an *empty* string - it stays `""`. Verified this gap concretely (`docker compose exec -e DJANGO_SECRET_KEY= ...` passed `check --deploy` with only a warning, not the intended hard failure) before broadening the condition to `if not SECRET_KEY or SECRET_KEY == "unsafe-development-key-change-me"`, then re-verified both the empty-string case (now raises) and the real-key case (still passes cleanly).

**Reviewed and confirmed already correct (no changes needed):** CSRF handling in the chat page's JS, structural per-user authorization on every trip/history/feedback view, no SQL-injection surface (all ORM-parametrized), AI-generated text rendered via `textContent` (no XSS path), and the Phase 15 Celery task's retry-safety/additive-only rules matching exactly what was approved.

**Noted but not acted on (deliberately, not urgent):** `recommendations.scoring.generate_recommendations()` calls the climate provider once per candidate destination in a loop - fine at the curated dataset's current size (18, Redis-cached), would need batching if the catalog grows substantially. The `Dockerfile` still installs `development.txt` and runs `manage.py runserver` rather than `gunicorn` (already present unused in `requirements/base.txt`) - correct for the current dev-only setup; switching to a real production image is a small, already-anticipated future step, not a current gap.

**Validation:** full suite re-run after both fixes - 115/115 tests passing, `ruff check .` clean. Docker stack brought back down afterward (review-only run, nothing needs to stay up).

---

## 2026-08-30 — Phase 16: Introduce Background Processing Where Needed

**Milestone:** Phase 16 (`15_IMPLEMENTATION_GUIDE.md` §20) - Owner: Joint Review.
**Goal per the guide:** "Only now should we identify which operations actually benefit from background processing... Do not move ordinary request/response work into background jobs simply because Redis exists."

**What was done:** a review, not an implementation. Went through each example the guide names and checked it against the current codebase:

- **Feedback processing** - already backgrounded in Phase 15 (`trips.tasks.update_traveler_preferences_from_feedback`). Nothing left to do.
- **Community aggregation** - `CommunityReview`/`AggregatedInsight` don't exist as models yet, deliberately deferred since Phase 4's domain-model design ("avoid speculative entities"). Nothing to background because the feature itself doesn't exist yet.
- **Non-critical notifications** - no notification system (email/push) exists anywhere in the project. Building one now to give Phase 16 something to background would be inventing a feature, not moving an existing one off the request/response path.
- **Provider synchronization** - the one plausible live candidate, surfaced by the post-Phase-15 revision's note that `recommendations.scoring.generate_recommendations()` calls the climate provider once per candidate destination, synchronously, on every recommendation request. A scheduled Celery Beat task pre-warming the Redis climate cache for all 18 curated destinations would be a legitimate "provider sync" background job in the abstract.

**Presented to the user as a choice** (close the phase with no new jobs vs. add the climate pre-warming task vs. something else) rather than deciding unilaterally, since the guide marks this phase's owner as Joint Review and its core task as identifying justified work, not manufacturing it. **User chose to close the phase with no new jobs.** Reasoning that holds up under scrutiny: at 18 destinations, backed by a free/fast API, with an existing 7-day cache already in place, a pre-warming job would only smooth out the first cache-miss request after each cache expiry - a small, unproven benefit. Building scheduled infrastructure (Celery Beat, a new periodic task, its own tests/monitoring) for that marginal a win would itself be the "background job simply because Redis exists" anti-pattern this phase explicitly warns against. Worth reconsidering later if the destination catalog grows enough that synchronous per-request climate fetching becomes a real latency problem - noted here so a future session doesn't need to rediscover the tradeoff from scratch.

**No code changes, no new tests, no migrations.** This phase's deliverable is the review record itself - `PROJECT_STATE.md` updated accordingly, current phase advanced to "Phases 0-16 complete."

---

## 2026-08-30 — Phase 17: Product Analytics

**Milestone:** Phase 17 (`15_IMPLEMENTATION_GUIDE.md` §21) - Owner: Human Decision + Claude Code.
**Goal:** measure whether people actually use TravelAgent, before significant public growth.

**Decision process** (full record in `DECISIONS_PENDING.md` §3): proposed three approaches (self-hosted first-party, self-hosted open-source tool, third-party hosted service) with tradeoffs; user chose **self-hosted, first-party** - consistent with every other infrastructure choice in this project (own Postgres, own auth, no vendor lock-in) and avoiding the privacy tradeoff of a third-party vendor. Also proposed deferring `premium_started`/`affiliate_link_clicked` since those features don't exist yet; user agreed. Iterated with the user on several follow-up specifics before implementing: whether to keep `recommendation_viewed` as a separate event (declined - no separate results page exists, the recommendation already appears inline in the chat stream), how to identify anonymous visitors (user chose IP over a session identifier, and any chat interaction - not just recommendation-type messages - should count), how to minimize that IP before storage (anonymized/masked, not raw), whether a cookie-consent step already existed anywhere in the docs (checked - it doesn't; GDPR consent is bundled into a later pre-launch review phase near Phase 30, not this one), and the exact "active user" definition (settled on: an authenticated user who interacted with the chat, windowed at 1/7/30 days for DAU/WAU/MAU).

**Implemented:**

- New `analytics` app: `Event` model (`event_type` from a fixed 6-value choice list, nullable `user` FK, nullable `anonymized_ip`, a small structured `metadata` JSONField, `created_at`), `analytics.services.record_event()` as the single write path, `analytics.metrics` module with `dau()`/`wau()`/`mau()`/`recommendations_per_active_user()`/`trips_per_active_user()`/`feedback_rate()`/`retention_rate()`, and a read-only Django admin registration (list/filter/search by event type, user, IP, with a date hierarchy) - the "dashboard" for a self-hosted, no-vendor approach.
- IP anonymization (`analytics.services._anonymize_ip`): zeroes the last IPv4 octet (`/24`) or masks an IPv6 address to its `/48` prefix, using Python's `ipaddress` module - the same technique privacy-conscious analytics tools use (Google Analytics'/Matomo's "IP anonymization" features). The raw address is never stored, never even passed further than this one function.
- `record_event()` never raises - a failure is logged at WARNING and swallowed, so a non-critical analytics write can never break registration, chat, trip creation, or feedback. This isn't backgrounded via Celery (a plain synchronous Postgres INSERT is cheap enough that doing so would itself be Phase 16's "background job simply because Redis exists" anti-pattern) - it's a foreground call with a safety net instead.
- Wired into six call sites: `users/views.py` (`user_registered` on successful registration; `profile_completed` in the profile view, guarded to fire only once - the first time the profile actually has content, not on every subsequent edit), `ai/views.py` (`travel_question_submitted` for literally any chat POST regardless of what it turns out to be, and `recommendation_generated` when the pipeline actually returns results), `ai/orchestration.py` (`feedback_submitted` and `trip_created` on the two conversational persistence paths - `_handle_feedback`/`_handle_future_intent` - tagged `metadata.source="chat"`), and `trips/views.py` (the same two events on the standalone form views, tagged `metadata.source="form"`), so both delivery channels for the same underlying action are measured together.
- A small, non-blocking transparency note added to `templates/base.html`'s footer (`{% blocktrans %}`, i18n-ready per the project's rule 5) disclosing anonymized usage-data collection - proposed as a middle ground once anonymous-IP tracking meant the app was collecting new personal(-adjacent) data starting today, without building a full consent-banner system that belongs to a later, pre-launch legal/GDPR review phase.

**A real design flaw caught before it shipped**: the `Event` model's first draft included a `CheckConstraint` requiring `user` or `anonymized_ip` to be non-null - a direct copy of the `Feedback` model's "destination or trip" constraint pattern. Unlike `Feedback`'s FKs (both `on_delete=CASCADE`), `Event.user` deliberately uses `on_delete=SET_NULL`, specifically so an authenticated event survives its user's account being deleted rather than distorting historical aggregate metrics retroactively. Those two choices actively conflict: Postgres enforces CHECK constraints on any row modification, including the UPDATE a SET_NULL cascade performs - so deleting any user with analytics history would have raised `IntegrityError` and silently blocked account deletion, a capability `11_SECURITY_&_PRIVACY.md` §12 explicitly requires ("Users should be able to delete their account and associated personal data"). Caught this by reasoning through the deletion path before writing tests, not by hitting the error in CI. **Fixed** by removing the DB constraint - the "user or IP" invariant is enforced by `record_event()` at write time instead, which is the only code path that ever creates an `Event` - and added a regression test exercising the SET_NULL path directly (`test_deleting_user_keeps_event_with_null_user`) so this can't silently regress.

**Validation:**

- 34 new tests: IP anonymization (IPv4 octet zeroing, IPv6 /48 masking, invalid/`None` input), `record_event` behavior (authenticated vs. anonymous, unknown event type ignored, missing request on an anonymous call skipped rather than crashing, metadata stored correctly, a mocked DB failure swallowed without raising), all six metric functions (DAU/WAU/MAU counting logic including that anonymous and non-chat events never count, per-active-user rates, retention across a cohort/return-window split), and wiring assertions at every one of the six call sites (including that a ratingless conversational feedback message does *not* record `feedback_submitted`, and that resubmitting the same future-intent doesn't double-count `trip_created`). 149/149 total tests passing, `ruff check .` clean, one new migration (`analytics.0001_initial`).
- **Verified live against the real running app**: confirmed the footer note actually renders on a real page (`curl` against `/users/register/`). Sent a real anonymous off-topic message through `/chat/` to the real OpenAI API - correctly recorded `travel_question_submitted` with `anonymized_ip` zeroed to a `/24` network address (the Docker bridge address seen by the container, `172.18.0.0` from `172.18.0.x`) and, correctly, no `recommendation_generated`. Then sent a real recommendation request ("somewhere warm in October, not too expensive") - recorded both events, and the reply matched the same Marrakech/Chiang Mai result already validated live back in Phase 9-11, confirming this instrumentation sits alongside the existing pipeline without disturbing it.

`DECISIONS_PENDING.md` updated with the full decision record (§3), `PROJECT_STATE.md` updated - Phase 17 done, current phase advanced to "Phases 0-17 complete."

---

## 2026-08-30 — Phase 18: MVP Validation (deploy-readiness prep)

**Milestone:** Phase 18 (`15_IMPLEMENTATION_GUIDE.md` §22) - Owner: **Human**. The phase itself is putting TravelAgent in front of real users (10 -> 100 -> 1,000) and learning from them - talking to users, watching behavior, collecting qualitative feedback, deciding what to build next. Claude Code's role is explicitly reactive: fix bugs, implement validated improvements, analyze structured usage data, improve tests.

**What this session actually is**: not the phase itself - there are no real users yet, and getting them is fundamentally a human action this session can't perform. What's done here is the practical prerequisite the phase depends on: the app has only ever run on `localhost`, so before any real user could reach it, it needed to be deployable somewhere real. Flagged this honestly rather than inventing work to look busy, and asked how the user wanted to proceed; they chose to prepare a real deploy now.

**Decision**: hosting provider. `12_DEVELOPMENT_&_DEPLOYMENT.md` §14 explicitly defers this ("the exact hosting provider can be selected later based on cost, reliability, geographic requirements, and operational simplicity") - treated it the same way as the Phase 2/3 provider decisions: proposed three options with tradeoffs (Render, Railway, Fly.io) rather than picking one unilaterally. User chose **Render**.

**Implemented:**

- **`Dockerfile`** restructured into more stages: `runtime` (the existing local dev/test image - unchanged, still installs `development.txt` with pytest/ruff, still runs `manage.py runserver`) and a new final stage, `production` - installs `requirements/production.txt` only, runs `collectstatic`, serves via `gunicorn config.wsgi:application` bound to `$PORT` (shell-form `CMD`, `["sh", "-c", "gunicorn ... --bind 0.0.0.0:${PORT:-8000}"]`, since the exec-array form can't expand environment variables). Made `production` the *last* stage deliberately - Render (and most PaaS platforms) run a plain `docker build .` with no `--target` flag, which builds whichever stage is last in the file, so no platform-specific target configuration is needed at all.
- **`docker-compose.yml`** updated to pin `target: runtime` explicitly on both `web` and `worker`'s `build:` config - without this, adding stages after `runtime` in the Dockerfile would have silently changed what `docker compose up` builds locally (Docker builds the last stage by default when no target is given). Reconfirmed with a full local rebuild: 149/149 tests passing, `ruff check .` clean, `/health/` still responds correctly - zero behavior change for local development.
- **`whitenoise`** added (`requirements/base.txt`; `WhiteNoiseMiddleware` placed directly after `SecurityMiddleware` per its own docs; `STORAGES["staticfiles"]` set to `whitenoise.storage.CompressedManifestStaticFilesStorage` in `config/settings/base.py`) - the simplest way for a small Django app to serve its own static files (mainly Django admin's CSS/JS, used to browse `analytics.Event` rows) under `gunicorn` without standing up a separate CDN or nginx, matching `12_DEVELOPMENT_&_DEPLOYMENT.md` §15's "simplest infrastructure" principle.
- **`config/settings/production.py`** gained two real, load-bearing (not cosmetic) additions on top of the post-Phase-15-revision fail-fast checks:
  - A fallback that reads Render's auto-injected `RENDER_EXTERNAL_HOSTNAME` env var and appends it to `ALLOWED_HOSTS` if present - solves the chicken-and-egg problem of not knowing the deployed hostname before the first deploy exists, without weakening the existing fail-fast-if-empty check.
  - `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")`. This one is not optional: Render (like most PaaS platforms) terminates TLS at a proxy in front of the app, so gunicorn only ever receives plain HTTP. Without this setting, `SECURE_SSL_REDIRECT = True` (already set, and correctly so) would have caused an infinite redirect loop in production - Django would see every request as insecure, redirect to HTTPS, the proxy would terminate that HTTPS request and forward it to gunicorn as HTTP again, and Django would redirect again. A well-known Django-behind-a-PaaS gotcha, worth calling out explicitly since it would only have surfaced once real traffic hit a real deploy - exactly the kind of failure this prep work exists to prevent. Also added `CSRF_TRUSTED_ORIGINS` derived from the (now-final) `ALLOWED_HOSTS` list.
- **`render.yaml`** (new): a Render Blueprint declaring `travelagent-web` (Docker, builds the `production` Dockerfile stage, health-checked at `/health/`), `travelagent-worker` (same image, `dockerCommand` overridden to `celery -A config worker -l info`), a managed Postgres database, and a managed Key Value (Redis) instance - directly mirroring `docker-compose.yml`'s four-service local split. Before writing this, used `WebFetch` against Render's live documentation (`render.com/docs/blueprint-spec`) rather than relying on possibly-stale training knowledge, specifically because Render has renamed and changed Blueprint fields over time (their Redis offering is now `type: keyvalue`, not the older `type: redis`; the worker service type is confirmed `type: worker`; `runtime: docker` is the current field, not an older `env: docker`). One real gap surfaced by that research and handled explicitly rather than glossed over: Render's Blueprint spec has no documented way to share one service's plain environment variable with another (`fromService`/`fromDatabase` only expose connection-style properties like `connectionString`) - so `DJANGO_SECRET_KEY` can't be automatically kept identical between `travelagent-web` (auto-generated via `generateValue: true`) and `travelagent-worker` (`sync: false`, must be copied by hand). Documented this both inline in the file and in the README, and noted it's currently harmless either way since the Celery worker never signs or verifies cookies, CSRF tokens, or sessions - but should still be kept matched as a matter of correctness, not left to drift.
- **README.md** gained a new "Deployment (Render)" section with the concrete human steps: connect the repo via Render's Blueprint flow, provide the `sync: false` secrets, run `migrate` + `load_destinations` once live, and add a custom domain later. Also fixed a stale instruction found in passing while editing this file: the existing Docker test command was still missing the `-e DJANGO_SETTINGS_MODULE=config.settings.test` override the Phase 15 investigation established as required - anyone following the README literally would have hit that same silent-wrong-settings bug again.

**Validation - as far as it can go without a Render account:**

- Rebuilt the local stack from scratch with `docker-compose.yml`'s new `target: runtime` pin: 149/149 tests passing, `ruff check .` clean, `/health/` responding - confirms the Dockerfile restructuring didn't change local dev/test behavior at all.
- Built the new `production` stage directly (`docker build --target production`) - succeeded, `collectstatic` ran cleanly (127 static files collected, 381 post-processed by whitenoise's compression/manifest step).
- Ran the resulting image as a real container against the existing local Postgres/Redis (over the same Docker network, real `DATABASE_URL`/`REDIS_URL`) and exercised the exact failure mode `SECURE_PROXY_SSL_HEADER` exists to prevent: a plain HTTP request correctly redirected to HTTPS (expected default behavior); the same request with `X-Forwarded-Proto: https` added (simulating what Render's proxy sends) did *not* redirect and served `/health/` correctly instead - confirming the proxy-header fix actually works, not just that it's present in the settings file. Also confirmed a static file (`/static/admin/css/base.css`) served correctly (200) via whitenoise. This is the strongest verification possible short of an actual Render deploy, which needs a real account - account creation and any payment/verification step is the user's to do, not something this session performs.

**Explicitly not done, correctly**: the actual Render deploy, and everything the guide means by "Phase 18" itself - talking to real users, watching behavior, collecting qualitative feedback, deciding what to build next. Those start once the user has deployed the app and has real people to show it to; `PROJECT_STATE.md` reflects this as "in progress," not "done."

`PROJECT_STATE.md` updated accordingly.

---

## 2026-08-30 — Out-of-sequence: site-wide CSS/JS pass

**Not a numbered guide phase** - a direct user request, prompted by an honest answer to "is the app ready to be used, with a finished frontend?" The honest answer was no: only `/chat/` had ever received any CSS (added back in Phase 10); every other page - registration, login, account, profile, trip CRUD, travel history, feedback - was confirmed (by actually reading the template source, not guessing) to be completely bare Django output: `{{ form.as_p }}` or a plain `<ul>`, zero styling, default browser fonts. This was a real, honestly-surfaced gap, not invented busywork - `08_FRONTEND_ARCHITETURE.md` always specified "Django templates + HTML + CSS + light JS, no React yet," and Phase 10's own task list included CSS, but only the chat page actually got any. User asked for enough CSS/JS to make the site "presentável e usável" - explicitly not a full redesign.

**Implemented:**

- `static/css/main.css` (new): one shared stylesheet using CSS custom properties for color/spacing - a persistent site header with navigation (auth-aware: authenticated users see Chat/My trips/My history/Profile/Account/a Log-out button; anonymous users see Chat/Log in/Register), styled forms (targeting the *existing* `{{ form.as_p }}` output directly - labels, inputs, checkbox-option lists, error lists - so most templates needed zero structural changes), buttons (`.btn`/`.btn-secondary`/`.btn-danger`), Django messages styled by their existing `message.tags` (success/error/warning/info - previously rendered as a bare, untagged `<li>`), and list/card styles for trips and travel history.
- `static/js/main.js` (new, ~25 lines): a mobile hamburger nav toggle and dismissible messages (adds a close button to each message, removes it from the DOM on click) - deliberately minimal, no framework, matching "light JS" from the architecture doc.
- `config/settings/base.py` gained `STATICFILES_DIRS = [BASE_DIR / "static"]` so Django's static file finder actually picks up the new source directory (only `STATIC_ROOT`/`STATIC_URL` existed before, for `collectstatic`'s output).
- `templates/base.html` restructured: added the header/nav markup, `{% load static %}` + `<link>`/`<script>` tags, `{{ message.tags }}` now rendered as a CSS class, and a new `content_class` block so most pages share a readable-width `.site-content` wrapper while a page needing full control over its own layout can override it.
- Roughly a dozen other templates got small, mechanical additions - a `class="btn"` on a submit button, `class="item-list"` on a bare `<ul>`, an `.actions` wrapper around a group of links - rather than any structural rewrite, since the shared stylesheet already targets plain HTML elements directly.

**Two real bugs found and fixed during this pass, both caught before being reported as done:**

1. **A regression risk to Phase 10's mobile viewport fix, caught by reasoning about it before it shipped, not by hitting it live.** `/chat/`'s `.chat-page` used `height: 100vh` on the assumption it was the only content on the page - true when it was written, no longer true once every page (including chat) gained a persistent header and footer. Naively wrapping chat in the same layout would have silently reintroduced the exact bug Phase 10 fixed (page taller than one viewport, `documentScrollHeight` far exceeding `window.innerHeight` on mobile). Fixed by giving `base.html` an overridable `content_class` block - chat overrides it to a flex-based `.content-flush` wrapper instead of the default `.site-content`, and `.chat-page` changed from a fixed `height: 100vh` to `flex: 1 1 auto` (fills whatever space the surrounding flex layout actually leaves). **Verified concretely, not just reasoned about**: used the Browser tool's `javascript_tool` against the real running page on an emulated 375x812 mobile viewport and confirmed `document.documentElement.scrollHeight` (812) exactly equals `window.innerHeight` (812) - zero page overflow, matching Phase 10's original fix exactly.
2. **A staticfiles-manifest failure that broke 23 of 149 tests the moment templates started using `{% static %}`.** `whitenoise.storage.CompressedManifestStaticFilesStorage` (added to `base.py` in the same-day Phase 18 deploy-prep work, earlier than this pass) requires a hashed manifest file that only `collectstatic` produces - which only ever runs in the `production` Docker stage, never in local dev/test. The moment `base.html` referenced `{% static 'css/main.css' %}`, every test rendering any page failed with `ValueError: Missing staticfiles manifest entry`. **Root-caused and fixed properly**: moved the manifest storage override out of `base.py` (now defaults to Django's plain `StaticFilesStorage`, which needs no manifest) into `config/settings/production.py` only. Investigating this surfaced a *second*, deeper version of the same bug: the `Dockerfile`'s `collectstatic` step deliberately ran under `development` settings (specifically to avoid tripping `production.py`'s fail-fast `ALLOWED_HOSTS`/`SECRET_KEY` checks at build time) - but with the manifest storage now living only in `production.py`, that meant the manifest would never actually be generated at all, and the real deployed app would have hit the identical `ValueError` in front of real users instead of in a test. Fixed by running `collectstatic` under `production` settings with throwaway, build-time-only `DJANGO_ALLOWED_HOSTS`/`DJANGO_SECRET_KEY` values (satisfying the fail-fast checks without needing real secrets at build time) instead of switching settings modules entirely. Verified by rebuilding the `production` Docker target from scratch and confirming, against a real running container, that the hashed static URL Django generates (`/static/css/main.<hash>.css`) actually resolves with a real HTTP `200`.
3. **Minor, caught visually rather than structurally**: an initial Unicode hamburger icon (`&#9776;`) risked rendering as an empty "tofu" box on systems whose font stack lacks that glyph. Replaced with a small CSS-drawn icon (three `<span>` bars) that has no font dependency at all.

**Validation:**

- 149/149 tests still passing after both settings fixes - no test needed changing, since none asserted on the previously-bare HTML in a way the added classes broke. `ruff check .` clean. Rebuilt the `production` Docker target from scratch to confirm the corrected `collectstatic` step still works end-to-end.
- **Verified live in a real browser**, not just automated tests: the desktop nav in both authenticated and anonymous states; the mobile nav toggle (confirmed via direct DOM inspection - clicking it adds the `is-open` class and flips `aria-expanded` correctly); a full real registration -> create-trip -> account flow rendering with the new styling; and the mobile chat-viewport-fit check described above.

No `PROJECT_STATE.md` phase-count change (this isn't a numbered phase) - added a dedicated checklist entry documenting what changed and why, under the Phase 18 entry it's most related to.

---

## 2026-08-30 — Bug fix: anonymous chat hard-blocked on login mid-conversation

**Reported directly by the user**, from a real conversation had via the just-styled UI: as an anonymous user, "someday between september and october" (answering the bot's own "what month are you planning to travel?" clarification question from two turns earlier) got the reply "you'll need to log in or create an account first" - a hard dead end. User's explicit requirement: an anonymous user must never be blocked from using the chat; the only difference for anonymous should be that preferences/history don't get saved.

**Root cause, found by reading the code, not guessing**: `ai.orchestration`'s intent classifier read the word "someday" in the message and classified it as `message_type: future_intent`, even though no destination was named at all - the prompt's guidance ("the user says they want to travel somewhere someday... without asking for a recommendation right now") triggered on the word alone, with no requirement that an actual destination be present. `_handle_future_intent` then checked `user.is_authenticated` *before* checking whether a destination was even extracted, so it hard-blocked on login immediately rather than ever reaching the "which destination did you have in mind?" fallback that already existed for exactly this incomplete-information case.

**Two fixes, both in `ai/orchestration.py`:**

1. **Classifier prompt tightened** (`INTENT_EXTRACTION_SYSTEM_PROMPT`): `future_intent` now explicitly requires a named or clearly-implied destination - "a message that only states timing... with no destination at all is NOT future_intent... classify it as 'recommendation' instead." Verified live against the real OpenAI API (not just reasoned about): the exact reported message now classifies as `recommendation`, not `future_intent`.
2. **`_handle_feedback`/`_handle_future_intent` reordered**: the "do we even have a destination name" check now runs *before* the login check, in both functions. This is deliberate defense-in-depth, not just a workaround for fix #1 - even a future misclassification (the classifier will not be perfect, especially given the orchestrator's documented lack of conversation memory) can no longer hard-block an anonymous user, since there's nothing to gate on login until a real, nameable destination is actually present. Two regression tests added (`test_feedback_without_destination_asks_instead_of_requiring_login`, `test_future_intent_without_destination_asks_instead_of_requiring_login`) exercise this ordering directly.

**A second, related gap found and fixed while verifying live**: even after fix #1, the same message still came back with `month: null` - the classifier had no instruction for what to do with a *range* of two months ("September and October"), so it left the field null despite two literal month names being present, then oddly asked "what destination are you considering" as its clarification question instead of proceeding. **Fixed**: added an explicit rule - a range of two consecutive months counts as stating a month; extract the earlier one. Re-verified live: `month` now correctly extracts as `9`.

**Known remaining rough edge, surfaced by this same live check, deliberately not addressed now**: even with both fixes, the model still sets `needs_clarification: true` and asks an odd "what destination" question for this exact message, rather than proceeding straight to a recommendation using `month=9` alone (which the recommendation pipeline can already do - `RecommendationRequest.month` is the only required field). This is a symptom of the orchestrator's documented, deliberate architectural gap - each chat message is classified in total isolation, with no memory of earlier turns (the "family of 4, calm and warm places" stated two messages earlier is invisible to this call). Prompt-tuning around a single isolated message has diminishing returns without real conversation memory to fix this properly - a materially bigger feature, not something to bolt on as part of a quick bug-fix pass. Flagged to the user rather than silently left unmentioned.

**Validation**: 151/151 tests passing (149 + 2 new regression tests), `ruff check .` clean. The core reported bug - hard login block - reverified live against the real OpenAI API and confirmed fixed twice: once after the classifier prompt fix, once more after the month-range fix, replaying the exact reported conversation both times.

---

## 2026-08-30 — Conversation memory (Redis-backed)

**User's direct follow-up** to the login-block bug fix above: "the known remaining rough edge you flagged - build real conversation memory for it, try to use Redis if possible." This closes the deeper architectural gap that fix could only route around: every chat message had been classified in total isolation, with zero awareness of earlier turns in the same conversation.

**Design**, grounded in `09_AI_ORCHESTRATION.md` §7's own distinction: **conversation context** (what's needed to understand the current exchange - short-lived, per-conversation) is explicitly separate from **traveler memory** (intentionally retained because it improves future experiences - already real: `TravelerProfile`, `Feedback`, `TravelHistoryEntry`, all in Postgres). This session only ever needed to build the first one; the second already existed. Redis was a natural fit for exactly that reason - ephemeral, expiring, never something to query or report on - and the user asked to use it if possible, which it clearly was: `django.core.cache` was already configured with a Redis backend (`config/settings/base.py`, used since Milestone 1) and already used this same way by `integrations.climate`'s own caching, so no new infrastructure was needed at all.

**Implemented:**

- `ai/memory.py` (new): `conversation_key(user, session_key)` - authenticated users keyed by account (`chat-history:user:{pk}`, so their conversation continues across devices/sessions), anonymous visitors keyed by their Django session (`chat-history:session:{key}` - the session framework was already there for auth cookies, just unused for anonymous visitors until now). `get_history(key)`/`append_turn(key, ...)` read/write a plain list of `{"role", "content"}` dicts via the existing cache, trimmed to the most recent `MAX_HISTORY_MESSAGES = 12` (6 turns) and re-expiring on every write (`CONVERSATION_TTL_SECONDS = 1800` - 30 minutes of inactivity resets the conversation). Both limits exist for the same reason `09_AI_ORCHESTRATION.md` §13 calls out explicitly: every remembered turn gets resent to the AI provider on every subsequent message, so unbounded history is a direct, ongoing cost, not just a memory-growth concern.
- `ai/orchestration.py`: `stream_travel_recommendation()`/`get_travel_recommendation()` gained a `session_key` parameter. History is loaded once at the top of the pipeline and passed into `_extract_intent()` (prepended as real conversation turns before the current message, ahead of the intent-extraction system prompt's own instructions) - this is deliberately the *only* call that gets history; `_build_explanation_messages()` (the second, per-request AI call that writes the final recommendation explanation) does not, to keep that call's grounding tight and avoid growing its cost too. Every branch - off-topic, feedback, future-intent, clarification, no-matches, the AI-failure fallback, and the full streamed explanation - now saves its own (message, reply) turn before returning, including on failure paths, so the next message always has full context regardless of how the previous one resolved. The streaming explanation path required care: the reply text isn't known until the stream finishes, so `_stream_explanation()` now accumulates chunks as they're yielded and saves the joined result in a `finally` block - runs whether the stream completes normally, hits a provider error mid-stream, or the client disconnects early, so a turn is never silently dropped from memory.
- `ai/views.py`: `recommendations_stream` now forces a Django session to exist (`request.session.save()` if no `session_key` yet) before calling the orchestrator, so even a visitor's very first message already has a stable identity to key conversation memory on - then passes `session_key=request.session.session_key` through.
- **A real test-isolation bug caught before it could cause flaky tests**: Django resets the database between tests (transaction rollback) but never touches the cache, and `config/settings/test.py` deliberately doesn't override `CACHES` (tests run against the real Redis-backed cache, consistent with this project's general preference for testing against real infra over substitutes). Without clearing it, anonymous conversation-memory tests sharing a cache key across test cases would silently leak state into each other. **Fixed** with a new root-level `conftest.py` - an autouse fixture calling `cache.clear()` before and after every test. Explicitly *not* the same `conftest.py` attempted and removed during the Phase 15 investigation (that one targeted Celery's eager-mode config and didn't work) - documented inline as a different, narrower fix that does work, so a future session doesn't conflate the two or wonder why a previously-removed file reappeared.

**Validation:**

- 13 new tests (`ai/tests/test_memory.py`: key derivation, empty-history default, accumulation, trimming; `ai/tests/test_orchestration.py`'s new `ConversationMemoryTests`: no history sent on a first message, a prior turn correctly appears in the second call's messages, two different anonymous sessions never share history, an authenticated user's history persists across different session keys, a fully-consumed streamed reply gets saved). 164/164 total tests passing, `ruff check .` clean.
- **Verified live against the real OpenAI API by replaying the exact three-message conversation that originally surfaced this whole investigation**: "what do you suggest for a destination?" -> "family of 4, calm and warm places" -> "someday between september and october", all under the same `session_key`. Confirmed via `_extract_intent()` directly that message 3's extracted intent carried `min_temp_c: 22` (the "warm" anchor from message 2, two turns earlier) and `month: 9` - context that was completely invisible to the pipeline before today. The full conversation then correctly produced 11 real, ranked recommendations (Marrakech, Hoi An, ...) instead of the login wall or the odd "which destination are you considering" clarification loop from the bug-fix commit immediately before this one.

No `PROJECT_STATE.md` phase-count change (not a numbered guide phase) - documented as a dedicated entry.

---

## 2026-08-30 — Bug fix: clarification loop on an optional field + warmer tone

**Reported live, via the just-shipped conversation memory**: the bot kept asking "What type of destination are you interested in (beach, city, nature, culture)?" on repeat, even after the user answered "low cost trip and a warm place" twice with no progress. User's second, related ask in the same message: make the AI sound friendlier, less like canned template text.

**Root cause**: `INTENT_EXTRACTION_SYSTEM_PROMPT` said `needs_clarification` should be true if the message "is missing information you would need - at minimum, a target month" - "at minimum" left the door open for the model to also gate on `trip_type` (explicitly documented elsewhere in the same prompt as optional, never to be force-fit), and it did exactly that, repeatedly, regardless of what the user actually answered. `_validate_intent()` had no code-level check tying `needs_clarification` to what `recommendations.scoring.RecommendationRequest` actually requires (only `month` - everything else defaults to `None`), so there was nothing stopping the model's own inconsistent judgment from looping indefinitely.

**Two fixes, both in `ai/orchestration.py`:**

1. **Deterministic validation** (`_validate_intent`): `needs_clarification` for a `recommendation` message is now decided in code, not trusted from the model - `True` only when `month` is genuinely missing/invalid, forced `False` whenever a valid month is present, regardless of what the model set. This is the load-bearing fix: it makes the loop structurally impossible, since the one field the pipeline actually requires is the one field validation checks - not something dependent on the model reliably following a prompt instruction under real conversational pressure.
2. **Prompt rewritten for tone and precision** (`INTENT_EXTRACTION_SYSTEM_PROMPT`): now states explicitly that month is the *only* thing that can trigger clarification; instructs the model to write `clarification_question` "the way Lunna... would actually talk to someone" - acknowledging what the traveler already said before asking what's missing, never as a bracketed list of categories to pick from; and explicitly forbids asking the same or a similar clarification question twice in a row once conversation history shows it was already asked and answered. This directly uses the conversation-memory feature shipped immediately before this fix - the model can now literally see it already asked, which it couldn't before today.

**Validation:**

- 1 new regression test (`test_month_present_never_needs_clarification_even_if_ai_says_so` - a stub AI provider that (mis)behaves exactly like the real model did live, setting `needs_clarification=True` with a `month` already present, asserts the app corrects it and returns real recommendations anyway). 165/165 total tests passing, `ruff check .` clean.
- **Verified live against the real OpenAI API**: replayed a conversation matching the reported one - "what do you suggest for a trip?" -> "low cost trip and a warm place" (twice) -> "sometime in July", all under the same session. The bot now consistently asks specifically about month ("Could you let me know what month you're thinking of traveling?" / "That sounds great! Just to make sure I suggest the best options for you, could you share what month you're planning to travel?") - never trip_type - and once July was given, immediately produced real, ranked recommendations (Marrakech, Hoi An, ...) correctly reflecting "warm" and "low cost" from two turns earlier. Confirmed the tone is noticeably warmer than the flat, listy phrasing from before the fix.

No `PROJECT_STATE.md` phase-count change (not a numbered guide phase) - documented as a dedicated entry, folded into the conversation-memory section above since the two are closely related (this bug was only fully diagnosable and testable because that feature had just shipped).

---

## 2026-08-30 — First real Render deploy: six real bugs found and fixed live

Before the user's first deploy attempt, one gap in the Phase 18 deploy prep was caught by reasoning through the actual Blueprint creation flow: `render.yaml`'s `DJANGO_SECRET_KEY` was split across `generateValue: true` (web, fills in silently) and `sync: false` (worker, prompts inline) - there would have been no way to know what value to paste into the worker's prompt, since it appears in the same form before the web service (and its silently-generated value) exists. Fixed by changing both to `sync: false`, with a README step to generate one random value upfront and paste it into both prompts.

**The user's actual first deploy attempt turned out not to go through the Blueprint flow at all** - a single service ended up created manually (only confirmed in retrospect: "só tem um serviço chamado wanderes"), so none of `render.yaml`'s automatic wiring (Postgres, Redis, the worker, env var linking) ever applied to it. This service did reveal one real, independent bug immediately: `https://wanderes.onrender.com/` 404'd, because the app never had a URL pattern for the empty path `""` (only `/chat/`, `/health/`, etc.) - invisible on `localhost` since nobody visits a bare `http://localhost:8000/` by habit the way they'd type a real domain. Fixed with `path("", RedirectView.as_view(pattern_name="ai:chat", permanent=False), name="root")` in `config/urls.py` (302, not 301, since a real landing page might replace this later and a 301 would get cached awkwardly). 1 new test (`core/tests/test_root_redirect.py`).

The same manually-created service's `/health/` returned `{"status": "degraded", "database": "unavailable"}` - persistently, not transiently. Diagnosed collaboratively over several rounds, each surfacing a real, independent bug rather than a one-off fluke of this botched deploy:

1. **`_database_is_reachable()` swallowed the real exception silently** - the access log only ever showed a generic 503, never the actual driver error. Added `logger.error(..., exc_info=True)` (`core/views.py`) so the next failing request would reveal the real traceback - this is what let the investigation proceed instead of guessing blind.
2. **The real traceback showed `OperationalError: ... "127.0.0.1", port 5432 ... Connection refused`** - `DATABASE_URL` wasn't set at all, so `base.py`'s hardcoded local-dev default was silently in effect. Root cause, confirmed once the user checked: no Blueprint had ever been applied, so `travelagent-db` never existed and nothing wired `DATABASE_URL` to this service. **No code fix here** - the user deleted the manual service and redid it via "New > Blueprint" properly, which resolved this by construction (this is exactly what `render.yaml` was written for).

**Once redeployed via Blueprint** (four real resources this time - `travelagent-web`, `travelagent-worker`, `travelagent-db`, `travelagent-redis`, at a new `travelagent-web.onrender.com` URL), `/health/` passed immediately and the root-redirect fix (already merged by this point) worked correctly. Three more real bugs surfaced from there:

3. **`travelagent-worker` crash-looped**: `RuntimeError: DJANGO_ALLOWED_HOSTS must be set in production.` `production.py`'s fail-fast check (a real, correct protection for the *web* service against Host-header attacks) also runs for the Celery worker, which imports the same settings module but never serves HTTP and has no `RENDER_EXTERNAL_HOSTNAME` to fall back to (no public URL). Fixed by adding `DJANGO_ALLOWED_HOSTS=celery-worker` to the worker's `envVars` in `render.yaml` - any non-empty value satisfies the check; nothing the worker does ever actually consults it.
4. **The worker still showed "failed" after that fix.** Its own startup banner showed `concurrency: 16 (prefork)` and the logs showed two "recovery" restart banners about 30 seconds apart - strongly suggesting Celery's default one-process-per-detected-CPU concurrency (16, on a `0.5c-512mb` plan) was spawning enough full Django/Celery process copies to exceed the plan's memory and get OOM-killed repeatedly. Fixed by adding `--concurrency=2` to the worker's `dockerCommand` - this app currently has exactly one lightweight, low-volume task (`trips.tasks.update_traveler_preferences_from_feedback`), nowhere near needing 16-way parallelism. (Also noted, not yet fixed: Celery logged a `SecurityWarning` about running as root inside the container - flagged to the user as a real but non-blocking hardening item for later.)
5. **`/api/v1/recommendations/` returned a 500**: `ProgrammingError: relation "django_session" does not exist` - migrations had never been run against the fresh database. Resolved by running `python manage.py migrate` from Render's Shell tab (a manual, one-time step per the README's deploy instructions - expected, not a bug).
6. **`load_destinations` then failed**: `FileNotFoundError: ... 'documentation/data/curated_destinations.json'`. Root cause, found by reading `.dockerignore`: it excludes `documentation/` from the Docker build context entirely (reasonable - developer docs don't need to ship in the image) - but the curated dataset is real application data the app reads at runtime, and it had been living inside `documentation/` since Phase 3/4. Invisible for the entire project so far because `docker-compose.yml` bind-mounts the whole project directory for local dev (`volumes: - .:/app`), which makes host files available inside the container regardless of what `.dockerignore` excludes from the *built image* - only a real deploy (no bind mount) could ever have surfaced this. **Fixed properly, not by touching `.dockerignore`**: moved the file to `travel/data/curated_destinations.json` - it's the `travel` app's own data, not documentation, so this is also a better home for it independent of the bug. Updated `travel/management/commands/load_destinations.py`'s `DEFAULT_DATASET_PATH`, `travel/models.py`'s docstring reference, and the pointers in `PROJECT_STATE.md`/`DECISIONS_PENDING.md`. Added `travel/tests/test_load_destinations.py` - the command had no test coverage at all before this, which is exactly how a broken default path could ship unnoticed; the new tests assert the default path actually exists and that running the command with no arguments actually creates destinations.

**Validation**: every fix in this entry was verified against the real, live Render deployment (not just locally) as the user worked through the deploy - each round's fix was confirmed by the user's next log paste or the next `curl`/browser check before moving to the next issue. The `travel/data/` move was additionally verified by rebuilding the `production` Docker target from scratch and confirming the file exists inside the built image this time (`docker run ... python -c "from pathlib import Path; print(Path('/app/travel/data/curated_destinations.json').exists())"` → `True`). 168/168 tests passing (2 new: the `load_destinations` regression tests, plus the root-redirect test), `ruff check .` clean throughout.

---

## 2026-08-30 — Bug fix: off-topic classification got "stuck"; the AI now replies in the user's language

**Reported live, once the deploy was actually usable**: "oi" (a bare greeting) correctly got the off-topic reply, but the next two messages - "quero viajar" and "i want to travel" - kept getting the *exact same* off-topic reply too, even though both are plainly (if vaguely) travel requests. User's second, related ask in the same message: the assistant should be able to respond in more than one language.

**Root cause**: `INTENT_EXTRACTION_SYSTEM_PROMPT` had no instruction telling the model to judge `message_type` from the current message alone - with conversation memory now feeding it the full history (shipped two commits earlier in this same session), the model appears to have anchored on the established "off_topic" pattern from the first turn rather than re-evaluating each new message on its own content. The prompt also never said a short, plain expression of wanting to travel ("I want to travel", "quero viajar") *is* a real recommendation request, just an incomplete one.

**Fixed in `ai/orchestration.py`** (`INTENT_EXTRACTION_SYSTEM_PROMPT`): added an explicit instruction to judge `message_type` from the current message only - "conversation history is context to help you understand the current message... never a pattern to keep repeating"; explicitly listed short plain travel-intent expressions as `recommendation`, not `off_topic`; and tightened the `off_topic` definition to genuinely unrelated/no-travel-content messages only.

**Multi-language support added** (`ai/prompts.py`'s `SYSTEM_PROMPT` and the same intent-extraction prompt): both now instruct the model to understand and reply in whatever language the traveler is writing in, not default to English. This covers everything the AI itself generates - clarification questions and the final recommendation explanation. **Known, accepted gap, not fixed here**: the fixed Python-string canned replies (`OFF_TOPIC_REPLY`, `NO_MATCHES_REPLY`, `FALLBACK_REPLY`, `NEEDS_LOGIN_REPLY`, and the feedback/future-intent acknowledgments) are still hardcoded English - they're deliberately not AI-generated (a past cost-consciousness decision, `09_AI_ORCHESTRATION.md` §13), so they can't dynamically match the user's language without either translating a fixed set of languages ahead of time or making them AI calls too. Flagged to the user rather than silently left unaddressed; no action taken pending their direction.

**Validation**: no new automated test - this is pure prompt-tuning to steer live model behavior, not a code-logic change with a deterministic path to assert on (existing stub-based tests already cover the `message_type` dispatch logic itself). 168/168 existing tests still passing, `ruff check .` clean. **Verified live against the real OpenAI API** by replaying the exact reported conversation: "oi" still correctly gets the off-topic reply; "quero viajar" now correctly classifies as `recommendation` and replies *in Portuguese* ("Que tipo de viagem você tem em mente? E em que mês..."); "i want to travel" (switching back to English mid-conversation) correctly replies in English - confirming the language match is per-message, not sticky to whichever language appeared first.

---

## 2026-08-30 — Bug fix: "no matches" dead end replaced with real AI reasoning

**Reported live**: a search for a beach destination, warm, for a family with 3 kids, in November returned the fixed canned reply ("I couldn't find a destination that fits... want to relax a constraint?") when the curated dataset's hard constraints eliminated every candidate. User's framing: "se ele nao encontra ele deve pedir mais informaçoes, e se a base de dados nao é o suficiente para decidir um destino ele deve usar a inteligencia da propria IA para decidir" (if it can't find one, it should ask for more information, and if the database isn't enough to decide, it should use the AI's own intelligence to decide) - directly extending the Phase 11 recommendation philosophy (the AI reasons from its own knowledge when the deterministic model has no answer) to this specific dead-end case, which had never actually been wired that way.

**Fixed in `ai/orchestration.py`**: the `if not results:` branch no longer returns the fixed `NO_MATCHES_REPLY` string. It now builds a real AI message (`_build_no_matches_messages()`) telling the model exactly which constraints were extracted and eliminated every curated candidate, and gives it an explicit choice: suggest 1-3 real destinations from its own general travel knowledge (clearly flagged as not from TravelAgent's verified data, since we don't have real pricing/climate for it) or ask a genuine clarifying question if the message truly didn't give enough to work with - the model's judgment call, not a fixed branch in the code. `NO_MATCHES_REPLY` removed entirely, now unused.

**Refactored while making this change**: the streaming/mid-stream-failure-fallback/conversation-memory-saving logic that the normal recommendation-explanation path already had (`_stream_explanation`, a nested closure) was extracted into a standalone `_stream_ai_reply(messages, message, *, ai_provider, remember)` function, since the new no-matches path needed the exact same behavior. Passes `ai_provider` and a `remember` callback explicitly rather than relying on closure variables, since it's no longer nested inside `stream_travel_recommendation` - avoids duplicating this logic a second time.

**Validation**: `test_no_matches_skips_the_explanation_call` (asserted zero AI calls happened) was rewritten as `test_no_matches_asks_ai_to_help_instead_of_a_dead_end_reply` (asserts the AI *is* called and its reply is used) - the old test's premise was the exact behavior being changed. 168/168 tests passing, `ruff check .` clean. **Verified live against the real OpenAI API**, two ways: (1) a realistic family-beach-November request that actually still matched real curated destinations (Zanzibar, Maldives) - confirming the normal path was untouched; (2) a deliberately unmatchable request (a 45°C beach in July) that genuinely hit zero results - confirmed the AI correctly recognized this was unrealistic and asked a warm, real clarifying question in Portuguese rather than returning a dead end.

---

## 2026-08-30 — Bug fix: "help me decide" no longer loops forever on month

**Reported live in the same conversation as the off-topic/language bug above**: a traveler explicitly said "eu nao sei ainda me ajude a decidir" (I don't know yet, help me decide) and later "nao sei o mes ainda me ajude a decidir" (I don't know the month yet, help me decide) - both times, the assistant just asked a differently-worded version of the same "what month?" question again, never actually helping. User's framing: the AI "parece um pouco burra... literalmente apenas programada" (seems a bit dumb... literally just scripted).

**Root cause**: the earlier fix that made `needs_clarification` deterministic (month is the only thing that can require it) had no escape hatch for a traveler who *explicitly declines* to give a month rather than simply not having answered yet - both cases looked identical to the validation logic (`month` is `None`), so both got the same repeated question forever.

**Fixed in `ai/orchestration.py`**: added a new `flexible_month` boolean to the intent-extraction schema and prompt - true when the traveler explicitly says they don't know/don't care, or asks the assistant to just decide (in any language/phrasing - "não sei", "me ajude a decidir", "you choose", "surprise me", etc.). In `_validate_intent()`, when this is true and no month was given, the app substitutes `date.today().month` (today's actual month) instead of asking again, sets `needs_clarification` to `False`, and marks `month_was_assumed = True`. `_build_explanation_messages()` now accepts `month_was_assumed`/`month` and, when true, tells the AI to mention transparently that it assumed the current month and the traveler can specify a different one - so the substitution doesn't happen silently. Also had to make the prompt state this "sticks" across later messages in the same conversation that move on to other details (trip_type, family, budget) without repeating "I don't know" - the first version reset back to asking for month the moment the traveler's next message didn't restate the same sentiment, since `flexible_month` is otherwise judged fresh per message like everything else.

**Validation**: 1 new regression test (`test_flexible_month_substitutes_current_month_instead_of_looping` - asserts `needs_clarification` becomes `False`, real recommendations come back, and the explanation call was told a month was assumed). 169/169 tests passing, `ruff check .` clean. **Verified live against the real OpenAI API** by replaying the exact reported conversation twice (before and after the "sticks across turns" refinement): first pass showed the assistant correctly proceeding with real recommendations (Lisbon, Kyoto, Cape Town) the moment "me ajude a decidir" was said, transparently mentioning "considerando que estamos no mês 8" - but then incorrectly reverting to asking for month again on the very next message (which only added beach/family details, without repeating the "I don't know"). Second pass, after the "sticks across turns" prompt fix, correctly carried the flexibility forward and gave a real beach recommendation (Zanzibar) without asking again.

---

## 2026-08-30 — Assistant renamed from "Lunna" to "Wander"

**Direct user request**, in the same message as the "help me decide" bug report. Straightforward rename across every user-facing and code reference:

- `ai/prompts.py`: `ASSISTANT_NAME = "Wander"` (was `"Lunna"`) - `SYSTEM_PROMPT` already built from this constant via an f-string, so it picked up the new name automatically.
- `ai/orchestration.py`: `OFF_TOPIC_REPLY` and the clarification-question style instruction inside `INTENT_EXTRACTION_SYSTEM_PROMPT` were both hardcoded string literals naming "Lunna" directly - both changed to reference the shared `ASSISTANT_NAME` constant (newly imported) instead of a second hardcoded string, so the name can't drift out of sync between the two files again.
- `ai/templates/ai/chat.html`: page `<title>` and `<h1>` updated.
- `README.md`: the two user-facing mentions ("talk to Lunna", the repo-tree description) updated.
- `CLAUDE.md`, `documentation/PROJECT_STATE.md`, `documentation/DECISIONS_PENDING.md`: these are current-state references (not historical narration like this log), so their "Lunna" mentions were updated to "Wander" directly, each with a short inline note recording the rename and its date - unlike this log, where past entries stay as an accurate record of what was true when they were written; this entry is where the rename itself is recorded chronologically.
- Noticed and fixed in passing while auditing `PROJECT_STATE.md`: its Phase 10 entry still described a "Lunna is thinking..." loading bubble - stale independent of this rename, since that text was already changed to "TravelAgent is thinking..." earlier in this same session but the tracking doc was never updated to match. Corrected for accuracy.

**Validation**: no test referenced "Lunna" anywhere, so nothing needed updating there. 169/169 tests passing, `ruff check .` clean. Verified live against the real OpenAI API and the real chat page: `OFF_TOPIC_REPLY` and a live model reply both now say "I'm Wander..."; the chat page's title and heading both say "Wander".

---

## 2026-08-30 — Bug fix: chat got permanently stuck re-asking already-answered questions

**Reported live, with a full transcript**: a real conversation gave the assistant a beach trip, family of 4, December, low budget, "relaxing and warm" - more than enough to work with - and it never once produced a recommendation. It kept re-asking for information already given (budget, "traveling alone or with someone") turn after turn, including after the user said "não tenho mais informações" (I have no more information) and, later, explicitly pointed out it had already answered ("já disse que vou viajar a família"). User: "ajsute isso ele ta fazendo perguntas as quais ja respondi, e diga o que houve" (fix this, it's asking questions it already got answered, and tell me what happened).

**Root cause, found by tracing the exact conversation against the real API with intermediate state printed at every step**: `ai_provider.generate_structured_reply()` - the intent-extraction call every branching decision in the pipeline depends on - had never had a `temperature` set, so it used OpenAI's default (1.0, high-randomness). Calling it twice with the *identical* message and conversation history could return meaningfully different extracted fields each time - confirmed directly: replaying the conversation showed a previously-established `flexible_month` context silently vanishing on the very next call with no new information to justify it. For a call whose entire purpose is feeding deterministic application logic (which pipeline branch runs, what gets queried), non-deterministic sampling was actively working against every one of the deterministic-`needs_clarification` fixes made earlier the same day - those fixes correctly acted on whatever the extraction returned, but the extraction itself wasn't stable turn to turn.

**Fixed**: added a `temperature` parameter to the `AIProvider.generate_structured_reply()` interface (`ai/provider/base.py`), threaded it through `OpenAIProvider`/`_complete()` (`ai/provider/openai_provider.py`) to the underlying API call, and had `ai/orchestration.py`'s `_extract_intent()` call it with `temperature=0` - the natural-language explanation/streaming calls are untouched and keep the provider's default, since variety there is fine (even desirable); only the structured-extraction call needed this. All in-repo stub AI providers (`ai/tests/test_orchestration.py`) and the real adapter's tests (`ai/tests/test_openai_provider.py`) updated to accept the new parameter; 1 new test confirms it actually reaches the underlying API call rather than being silently dropped.

**Validation**: 170/170 tests passing, `ruff check .` clean. **Verified live against the real OpenAI API** by replaying the exact reported conversation again: the catastrophic failure mode - never converging, looping forever regardless of how much information was given - is gone. Real recommendations (Zanzibar) now come back at multiple points in the conversation, and the one genuine no-match turn (December + beach + warm + very-low-budget together, which the curated dataset can't satisfy) correctly asks a single reasonable follow-up instead of looping. One smaller, non-catastrophic rough edge remains and was reported honestly rather than glossed over: one specific turn (a message that only adds `trip_type` with no new timing information) still occasionally re-asks for month once before the conversation stabilizes - `flexible_month`'s "stays true across turns" instruction is more reliable now with `temperature=0` but not perfectly so on every single turn. This is a materially smaller problem than the one reported (the chat still converges to a real answer within one extra turn, not never) and was not chased further in this pass.

---

## 2026-08-30 — Architectural fix: removed the clarification gate entirely, never blocks on missing criteria

**The user pushed back on all the fixes above**, correctly: "vc nao ta resolvendo o problema geral ta so remediando as coisas" (you're not solving the general problem, just patching things). Their actual complaint, verbatim: "o problema em si e a falta de raciocinio da IA, ela parece que ta so seguindo um roteiro... ela precisa ter a capacidade de trazer resultados quando nem todos os criterios forem cumpridos deixando esse criterios como nao relevantes" (the real problem is the AI's lack of reasoning, it looks like it's just following a script - it needs the ability to bring results when not all criteria are met, treating those criteria as not relevant). This is a materially different, correct diagnosis: every fix so far (temperature=0, flexible_month, the no-matches AI fallback) still operated *within* a design where `needs_clarification` could gate the whole pipeline before a single search was ever attempted - a rigid, form-filling shape, not a reasoning one.

**Traced the actual remaining gate**: `_validate_intent()` still forced `needs_clarification = True` whenever `month` was missing (the one field genuinely required for a climate lookup), even after `flexible_month` softened the "explicitly declines to answer" case. Every *other* field (`trip_type`, `min_temp_c`, `max_cost_of_living`) was already correctly treated as "unspecified = not relevant, don't filter" - `month` was the one dimension still allowed to block the conversation before any real attempt at an answer.

**The actual architectural fix, not another patch**: removed the clarification gate and everything supporting it, structurally rather than relying on the model reliably choosing not to use it:

- `INTENT_SCHEMA`: removed `needs_clarification`, `clarification_question`, and `flexible_month` entirely. This is a hard guarantee, not a prompt suggestion - OpenAI's strict JSON schema mode means the model *cannot* emit fields that don't exist in the schema, so this class of "ask instead of answering" behavior becomes structurally impossible rather than just discouraged.
- `INTENT_EXTRACTION_SYSTEM_PROMPT`: rewritten to state plainly that every field is optional and none should ever trigger a follow-up question - "a real person will rarely state every dimension in one message... leaving one null just means the application treats that dimension as not relevant/unconstrained, not as something missing to chase."
- `_validate_intent()`: `month` missing/invalid now unconditionally defaults to `date.today().month` (no more "only if flexible_month was signaled" branch) - the same treatment every other field already got. `stream_travel_recommendation()`'s clarification branch (`if intent["needs_clarification"]:`) is gone entirely; the pipeline always proceeds straight to a real search.
- `_build_no_matches_messages()`: previously gave the AI a choice between "suggest from general knowledge" or "ask a clarifying question" - live testing during the earlier fixes showed it was choosing "ask" far too often, even with plenty of information already given. Rewritten to always instruct suggesting from general knowledge, relaxing whichever constraint made the curated data come up empty; asking is now reserved for the (structurally rare) case where the message truly gives nothing at all to work with.
- `OrchestrationResult`/`StreamingOrchestrationResult` (`needs_clarification: bool` field) removed entirely, since nothing outside `ai/orchestration.py`'s own tests ever read it and every code path now always returns the same value for it. Matches "delete code you're certain is unused" rather than leaving dead weight behind a redesign.

**Tests**: removed the tests whose entire premise no longer exists (`test_month_present_never_needs_clarification_even_if_ai_says_so`, `test_flexible_month_substitutes_current_month_instead_of_looping` - both regression tests for bugs in a mechanism that's now gone rather than fixed) and rewrote the ones testing missing/invalid month to confirm the new behavior (defaults automatically, real recommendations come back, no question asked). 168/168 tests passing, `ruff check .` clean.

**Validation - the real test**: replayed the *exact* reported conversation (beach, family of 4, December, low budget, "relaxing and warm", "I have no more information", "I already told you...") against the real OpenAI API from scratch. Every single message now returns real recommendations (18, then 4, then 1, then 1, then 1) - including the final message, which hits every hard constraint at once (December + beach + 28°C + cost tier 2) and genuinely matches nothing in the curated dataset, yet still returns a real suggestion ("Praia do Forte, Brasil") from the AI's own general knowledge instead of yet another question. Zero clarifying questions anywhere in the replayed conversation - the structural fix, not luck.

---

## 2026-08-30 — Second round of feedback: still feels scripted, not like a real AI

**The user tried the fix above and immediately found two more real problems**, both direct continuations of the same underlying critique:

1. Opened a fresh conversation with "oi pode me ajudar com uma viagem?" (hi, can you help me with a trip?) - completely open-ended, no month/climate/budget/destination at all - and got three specific destination suggestions ("Praia do Forte", "Lisboa", "Maldivas") immediately. User: "pq ele saiu em dando destinos? eu nem falei nada" (why did it just start giving destinations? I didn't even say anything) - "não é pra sair dando dados, é pra tentar recolher informações, mas caso não consiga e o usuário pedir destinos aí sim deve dar" (it's not supposed to just start giving data, it's supposed to try to gather information, but if it can't and the user asks for destinations, then yes it should give them).
2. Asked "vc é uma ia?" (are you an AI?) and "quantos anos vc tem?" (how old are you?) back to back - both got the *exact same* verbatim `OFF_TOPIC_REPLY` string. User: "como disse nao ta parecendo uma IA mas apenas um if else que se sai fora disso ela nao consegue reacioncinar" (like I said, it doesn't seem like an AI, just an if/else that can't reason once it's outside that) - then the explicit direction: "Quero que configure pra funcionar como uma IA tipo chatgpt,grok ou deepseek. Mas voltado pra viagens e se o usuario perguntar algo muito fora do assunto ai sim ela deve dizer que so entende de viagens" (configure it to work like ChatGPT/Grok/DeepSeek - focused on travel, and only when something is genuinely off-topic should it say it only understands travel).

Both point at the same architectural gap the previous fix didn't touch: two response paths were still **not AI-generated at all**. `off_topic` returned the literal same Python string every time, no matter what was actually asked. And the "nothing extracted" case (previously just logged and then still ran an unfiltered search across all 18 curated destinations) skipped straight to suggestions instead of a natural opening question.

**Fixed, in both `ai/prompts.py` and `ai/orchestration.py`:**

- `SYSTEM_PROMPT` rewritten to explicitly license natural reasoning: ask real follow-up questions when there isn't enough to make a good suggestion yet (the way a human consultant would), give real answers once there is; treat a brief, reasonable question about the assistant itself (is it an AI, its name, how it works) as a normal thing to answer honestly and briefly, not a violation to refuse; only decline and redirect when a message is genuinely unrelated to *both* travel and the assistant - and even then, in the model's own words, "never the exact same canned sentence twice."
- `off_topic` no longer returns the fixed `OFF_TOPIC_REPLY` string (removed entirely, along with the now-unused `ASSISTANT_NAME` import it needed). It now makes a real AI call (`_build_off_topic_messages()` - just `SYSTEM_PROMPT` + the actual message, letting the model's own judgment handle it per the rules above) through the same `_stream_ai_reply()` infrastructure the recommendation/no-matches paths already use.
- New "genuinely nothing extracted" handling: previously, a message with no month/trip_type/temperature/budget/exclusions still ran a full unfiltered search (returning essentially the whole 18-destination catalog) and let the explanation call pick a few - which is exactly what produced the unwanted immediate suggestions. Now, when `has_any_signal` is false (nothing at all extracted, including no explicitly-stated month), the pipeline skips the search step entirely and makes a dedicated AI call (`_build_open_ended_messages()`) that hands the *actual judgment call* to the model: ask a genuine follow-up if this reads like the start of a conversation, or suggest 2-3 real destinations from general knowledge if the message already explicitly invites a guess (e.g. "surprise me"). This is deliberately not a Python rule deciding ask-vs-answer - that's exactly the "if/else, not an AI" pattern being fixed.
- The Phase 11 "relying on AI judgment over the full candidate list" logging (for the case where *some* signal - at minimum an explicit month - was given but no scoring dimension matched, e.g. "a romantic getaway in June") was preserved as its own, separate check, since that's a materially different situation from "nothing given at all" and still deserves its own observability.

**Tests**: rewrote the two off-topic tests that asserted zero AI calls happened (their premise is now the opposite of correct behavior) to assert a real AI call *does* happen and its reply is used; added a new test for the "completely open-ended message" path confirming it skips the search and streams an AI-decided reply instead; fixed one test whose `_intent(month=42)` input (invalid month, nothing else) now correctly routes through the new open-ended path instead of a search - added a real signal (`min_temp_c`) so it still tests what it originally meant to (invalid month input handled gracefully, not crashing). 169/169 tests passing, `ruff check .` clean.

**Validation - replayed the actual reported exchange against the real OpenAI API**: "oi pode me ajudar com uma viagem?" now asks a genuine, varied follow-up question about destination/budget/timing instead of listing destinations. "vc é uma ia?" gets an honest, natural "yes, I'm an AI here to help you with travel" - not the canned sentence. "quantos anos vc tem?" gets a *different*, contextually appropriate answer about being a virtual assistant without an age - proving the replies actually vary based on what's asked, not a second hardcoded string. As an extra check, asked something truly unrelated ("qual a capital da frança?") - the model answered it briefly and naturally, then steered back to travel on its own ("Você está pensando em visitar Paris?") - closer to how a real assistant like ChatGPT actually behaves than a hard refusal would be, while staying anchored to the product's travel focus.

---

## 2026-08-31 — Real production deploy completed by the user; three more chat/CSS bugs fixed

**The user completed the actual Render Blueprint deploy themselves** (Phase 18's "MVP Validation" is explicitly Human-owned per `15_IMPLEMENTATION_GUIDE.md` §38) - reported the Blueprint ID, that `/health/` was returning healthy, and separately that the worker service showed as "failed." Diagnosed from pasted Render logs across several exchanges (all resolved, documented in the earlier "First real Render deploy" entry this same log covers): `DJANGO_ALLOWED_HOSTS` missing for the worker (a Celery process has no `RENDER_EXTERNAL_HOSTNAME` since it's not HTTP-facing), then a worker OOM from unbounded/high Celery concurrency on a 512MB plan, then migrations that had never been run, then a `load_destinations` `FileNotFoundError` (the curated-destinations JSON lived under `documentation/`, which `.dockerignore` excludes from the image - moved to `travel/data/`). Site is now fully live and healthy at https://travelagent-web.onrender.com/.

**After the deploy, the user reported three more real problems**, with a full pasted transcript for the first: "quero que me ajude a montar minha viagem de fim de ano" (help me plan my year-end trip) got an immediate list of three unrelated destinations (Rio, Lisboa, Tóquio) with zero information given; "mudei de ideia quero abril do ano q vem" (changed my mind, want April next year) got "That sounds exciting - which destination did you have in mind?" (visibly the `future_intent` handler, despite no destination being named); "quero algo em familia" (something for family) again jumped straight to three destinations (Algarve, a garbled "Câncios, França", Costa Rica). User, verbatim: "olhe essa conversa ele nao ta tentando extrair informaçoes, mantem jogando destinos na cara do usuario e nao é isso qu queremos" (look at this conversation, it's not trying to extract information, it keeps throwing destinations in the user's face and that's not what we want). Same message also reported the chat input bar not staying visually pinned - had to keep scrolling to find it.

**Bug 1 - input bar not pinned, root cause found empirically**: rather than reasoning about the CSS in the abstract, simulated a 40-message conversation directly in a live browser and measured real DOM values. Confirmed: `document.documentElement.scrollHeight` (3335px) far exceeded `window.innerHeight` (1274px), and critically `.chat-messages`'s `scrollHeight` equaled its `clientHeight` (3043 = 3043) - meaning it never actually clipped/scrolled internally at all, despite having `overflow-y: auto` set. The whole page grew instead. Root cause: `body { min-height: 100vh }` in `static/css/main.css` is a *floor*, not a ceiling - when content wants to be taller than one viewport, `min-height` lets `body` grow to fit it rather than giving the flex chain (`.content-flush` → `.chat-page` → `.chat-messages`, which already correctly had `min-height: 0`/`flex: 1 1 auto` at every level) an actual bounded box to squeeze into. Fixed by adding `height: 100dvh` alongside the existing `min-height: 100vh` (kept as a fallback for browsers without `dvh` support; `dvh` accounts for mobile browser chrome better than `vh`). Verified after the fix, same simulated-conversation approach: `.chat-messages.clientHeight` (982px) is now genuinely less than its `scrollHeight` (3043px) - it scrolls internally - while `document.documentElement.scrollHeight` stays exactly at `window.innerHeight`, and the input bar's bounding rect stays within the visible viewport on both desktop and a mobile-emulated viewport. Also explicitly verified the fix doesn't regress normal pages: `/trips/` with 60 injected paragraphs still grows `document.documentElement.scrollHeight` well past one viewport and scrolls normally - the constraint only bites where `min-height: 0` is set (the chat page), since `.site-content` (used everywhere else) was never given that, so it keeps its natural content-driven size and overflows the body box visually exactly as before.

**Bug 2 - "still throwing destinations," root cause found**: `stream_travel_recommendation()` had two separate checks that were never actually merged - `has_any_signal` (gated whether to search at all) and `no_scoring_signal` (computed and logged, but never gated anything). A bare month (stated or defaulted from "today") or an exclusion alone satisfied `has_any_signal`, so the pipeline proceeded straight into `generate_recommendations()` against the full curated dataset and then explained whatever came back - this is exactly what produced Rio/Lisboa/Tóquio off a message that gave literally nothing but "year-end," and Algarve/France/Costa Rica off "something for family" (a vibe with no mapping to `trip_type`, `min_temp_c`, or `max_cost_of_living`, all three of which are the only fields that actually differentiate one curated destination from another). Fixed by collapsing both checks into a single `has_differentiating_signal` gate on exactly those three fields - month and exclusions are real signal, but not enough on their own to justify running a search; they now route through the same AI-judgment "ask a genuine follow-up, or suggest if the traveler already explicitly invited a guess" path (`_build_open_ended_messages()`) already built for a fully blank opener in the previous fix. That helper now also takes `intent` as a parameter, so it can tell the model what weaker signal (a stated month, an exclusion) is already known - the prompt explicitly says "don't ask about it again, just build on it" - keeping the "never repeat an already-answered question" principle intact even though the search-gating logic changed underneath it.

**Bug 3 - `future_intent` misclassification fixed**: "mudei de ideia quero abril do ano q vem" names no destination at all, yet was classified as `future_intent`. The existing prompt rule already said a timing-only message shouldn't count as `future_intent`, but never addressed desire/intent language ("quero", "mudei de ideia") without a destination - the model appears to have keyed off "quero ir" (want to go) as intent-to-visit rather than reading that no place was actually named. `INTENT_EXTRACTION_SYSTEM_PROMPT`'s `future_intent` rule broadened explicitly: "wanting to travel, changing your mind, or expressing eagerness/excitement is not future_intent by itself," with the exact reported phrase given as a worked example of what should fall back to `recommendation` instead.

**Tests**: `test_logs_when_no_deterministic_constraints_extracted` renamed to `test_logs_when_no_differentiating_signal_extracted` and its assertion updated for the new merged check's log message (its `_intent(month=6)` input now correctly routes to the open-ended path instead of a search, matching the new behavior it exists to lock in). `_build_open_ended_messages()`'s new `intent` parameter required no other test changes - every other test already either supplies a differentiating field (still routes to search, unaffected) or calls `_intent()` with everything null (still routes to open-ended, unaffected). 169/169 tests passing, `ruff check .` clean.

**Validation - all three fixes verified live against the real OpenAI API and the real rendered page**, replaying the exact reported conversation from scratch: "quero que me ajude a montar minha viagem de fim de ano" now gets "Você já tem algum destino em mente ou está aberto a sugestões?" - a genuine follow-up, zero destinations named. "mudei de ideia quero abril do ano q vem" now gets "Entendi que você mudou de ideia... Que tipo de experiência você está procurando?" - correctly acknowledges the change, asks about trip type, never asks for a destination. "quero algo em familia" now gets a follow-up about what kind of activity the family wants, not three destination names. As a check against over-correcting into *always* asking, sent "surpreenda-me, escolha você" (surprise me, you choose) as a follow-up - it correctly *did* suggest real destinations (Costa Rica, Bali) reasoning from the nature/relaxing context already established in the conversation, confirming the AI-judgment path still works in both directions. The CSS fix was confirmed in this same live session (see Bug 1 above) with the input bar staying visible throughout the whole exchange.

---

## 2026-08-31 — Requested AI-intelligence audit: found and fixed a spurious temperature-inference bug

**The user asked for a broad round of live testing** ("faça diversos tests para verificar a inteligencia da IA pois ela ainda parece confusa" - run various tests to verify the AI's intelligence, it still seems confused) rather than reporting one specific bug - so this entry covers a deliberate testing pass, not a single reported failure.

**Method**: drove the real chat endpoint directly via `fetch()` in a live browser against the real OpenAI API (bypassing UI clicks for speed), flushing the Redis conversation-memory cache between independent scenarios to keep them isolated. Covered: a multi-criteria message in one shot, gradual multi-turn build-up, a mid-conversation preference correction plus a language switch (Portuguese to English), a feedback-then-exclusion flow, and a self-referential question ("are you an AI?") interrupting a recommendation flow. Most of these came back clean - trip_type corrections, language switching, exclusions, and off-topic interruptions were all handled correctly with no repeated questions and no loss of context.

**One real bug found**: a multi-turn scenario ("praia" -> "mais ou menos em julho" -> ...) unexpectedly fell back to the AI's general-knowledge no-matches path instead of returning real curated destinations. Traced by calling `_extract_intent()` directly (bypassing the full pipeline) with hand-crafted inputs to isolate the cause: `min_temp_c` was coming back as `28` even for messages that never mentioned temperature at all - "praia em julho" ("beach in July") alone was enough to trigger it, while "praia" alone was not, and this was perfectly *consistent* across repeated identical calls (temperature=0 doing its job - this was a genuine prompt-following gap, not sampling noise). The initial hypothesis - that conversation history (specifically the assistant's own prior reply, which mentions real destination temperatures) was leaking into the next extraction call - turned out to be a red herring: the same failure reproduced with an empty history, so it wasn't a history-poisoning bug at all. The real cause: gpt-4o-mini was inferring "if they're naming a beach trip for a specific month, they probably want to know it'll be warm then" and silently filling `min_temp_c=28`, directly against the existing "leave null unless the user's own words describe temperature" instruction - the model just wasn't following that rule reliably for this specific trip_type+month combination.

**Fixed** by strengthening `INTENT_EXTRACTION_SYSTEM_PROMPT` (`ai/orchestration.py`) in two passes, verified against the live API after each: first, an explicit statement that a trip_type or destination never implies a temperature or budget by itself, no matter how stereotypical the association (a beach trip isn't automatically "hot"); second - since the first pass alone didn't fix the specific "trip_type + month" combination - a concrete worked counter-example naming the exact failure pattern ("'praia em julho'/'beach in July' has a trip_type and a month but says nothing about temperature... do not reason 'they mentioned a month for a beach trip, so they probably want to know it'll be warm then'"). Concrete examples succeeded where the abstract rule alone didn't. Also added a general instruction that the assistant's own prior replies in conversation history (which mention real destination temperatures/cost tiers when explaining suggestions) should never be mistaken for something the traveler stated - kept as reasonable defense-in-depth even though it wasn't what caused this particular bug.

**Validation**: re-ran the direct-extraction harness after each prompt change - "praia em julho" now correctly returns `min_temp_c: null`, while "quero uma viagem de praia bem quente" (explicitly "very hot") still correctly returns `28`, confirming the fix is precise rather than just suppressing the field entirely. Spot-checked `cidade em dezembro` and `algo cultural em outubro` (other trip_type+month combinations) - both correctly leave temperature/budget null. Replayed the full originally-broken conversation end-to-end through the real chat endpoint: all four turns now return real curated recommendations instead of falling back to general knowledge. 169/169 tests passing, `ruff check .` clean - note this specific class of bug (a live model not perfectly following a prompt instruction) isn't something the mocked test suite can catch or guard against, since `StubAIProvider` always returns exactly what each test tells it to; the only real verification for this kind of fix is live, against the actual model, which is what was done here.

**Second finding, raised as a product decision rather than fixed unilaterally**: `_handle_feedback()`/`_handle_future_intent()`'s templated acknowledgment strings ("Thanks! I've recorded your feedback on Zanzibar: 9/10.", `NEEDS_LOGIN_REPLY`, the "which destination did you have in mind?" prompts) were hardcoded English regardless of what language the rest of the conversation is in - reproduced live: a full Portuguese conversation giving feedback got one jarring English sentence mid-flow. These were deliberately made non-AI templates on 2026-08-29 specifically to avoid a second AI call per message (Phase 14/the "chat handles more than recommendations" entry) - a decision that predates the later, separate "the site should respond in more than one language" request, and the two were now in tension for these specific paths. Presented three options (per-language template table with no extra AI cost but limited language coverage; accept a small extra AI call to cover any language; leave as-is) - **the user chose to accept the extra AI call**.

**Implemented**: new `_localize_reply(fact, *, message, ai_provider)` helper in `ai/orchestration.py` - takes a fact the application has *already fully decided* (what changed, whether it succeeded) and makes one small non-streaming `generate_reply()` call asking the model to say exactly that fact in its own natural words, in the same language the traveler is writing in. Deliberately narrower than every other AI call in this module: it's never asked to decide anything, only to phrase an already-fixed fact - so it can't introduce the kind of reasoning drift the rest of this session's fixes were about. `_handle_feedback()`/`_handle_future_intent()` now route every one of their return branches through this instead of returning the raw fact string directly; both gained `message`/`ai_provider` parameters, threaded from their one caller in `stream_travel_recommendation()`. On an `AIProviderError`, `_localize_reply()` degrades to returning the fact as-is (correct information, just not localized that one time) rather than losing the confirmation.

**Tests**: `StubAIProvider`/`FailingAIProvider` (`ai/tests/test_orchestration.py`) gained a `generate_reply()` method - the stub echoes back the exact fact text it was asked to phrase (stripping the wrapping instruction), which kept every existing assertion against the original English fact strings (`NEEDS_LOGIN_REPLY` exact-match, `assertIn("which destination", ...)`, `assertIn("lisbon", ...)`) valid unchanged - actual localization quality is a live-only concern no mocked stub can meaningfully exercise, consistent with the temperature-inference fix earlier in this same entry. 169/169 tests passing, `ruff check .` clean.

**Validation - verified live against the real OpenAI API**: replayed the Zanzibar feedback conversation from earlier in this entry - "fui pra Zanzibar ano passado, adorei..." now gets "Entendi - anotei que você visitou Zanzibar. Se quiser, pode me contar como você o classificaria de 1 a 10!" (fully natural Portuguese, not the old literal English template), and "quero ir pra Bali algum dia" gets "Entendi! Adicionei Bali aos seus planos de viagem para algum dia." Also checked the login-gated path logged out: "fui pra Roma mes passado, adorei tudo, nota 10" correctly explains (in Portuguese) that login is needed before it can be saved - the previously-hardcoded `NEEDS_LOGIN_REPLY` sentence is now localized too.
