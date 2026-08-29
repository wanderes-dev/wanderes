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
