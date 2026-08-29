# Project State (resume point)

> Purpose: let Claude (in any future session) resume exactly where the last session left off, without re-reading the entire conversation history. Update this file every time meaningful progress is made or the project pauses. This is the single source of truth for "where did we stop."

**Last updated:** 2026-08-29
**Current phase:** Phases 0-13 complete. There is a working, live-validated chat UI at `/chat/` — start it with `docker compose up -d` and open http://localhost:8000/chat/ (see README). `OPENAI_API_KEY` is configured in `.env` (never committed). Phase 11 (Joint Review) found and fixed real gaps and closed with an explicit human decision on recommendation philosophy. Phase 12 (Travel History) added `TravelHistoryEntry` + CRUD. Phase 13 (Trip Management) added full `Trip` CRUD plus "save this recommendation as a trip" directly from the chat page — the whole loop (chat → recommendation → save → view trip) works for real, live-tested. Repo is pushed to https://github.com/wanderes-dev/wanderes.git (remote `origin`, branch `master`). Next: Phase 14 (Feedback).

**Product decision (2026-08-29):** UI is English-only for now, built translation-ready (`LocaleMiddleware`, `LOCALE_PATHS`, `LANGUAGES` already configured — see `CLAUDE.md` rule 5). Working/communication language with the user also switched to English as of this date.

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
- [x] **Phase 3 — Select travel data providers** ✅ Decided 2026-08-28: **curated static dataset** for destination data (name/country/description/POIs) + **Open-Meteo** for real climate data, both behind the internal Travel Data Interface. Flights/hotels deferred per the MVP plan. See `DECISIONS_PENDING.md` §2. Initial curated destination list (18 destinations) drafted and approved 2026-08-29 — stored at `documentation/data/curated_destinations.json`. **Adapters (Open-Meteo client + destination data access) not yet implemented — next actionable step.**
- [x] **Phase 4 — Define initial domain models (Joint Review)** ✅ Done 2026-08-29. Proposed, reviewed/iterated, and implemented. See `DEVELOPMENT_LOG.md` for the full design discussion. Summary:
  - `users.User` — custom user model, **email-based login** (no username field). Google OAuth is a planned future login method (per user request) but **not implemented yet** — deferred, same as `14_MVP_IMPLEMENTATION_PLAN.md` Milestone 2 originally specified.
  - `users.TravelerProfile` — deliberately minimal (preferred trip types, preferred cost-of-living tier).
  - `travel.Destination` — shaped to match `documentation/data/curated_destinations.json` exactly; loadable via `python manage.py load_destinations`.
  - `trips.Trip`, `trips.TripFlight`, `trips.TripAccommodation`, `trips.Feedback` — `TripFlight`/`TripAccommodation` are real relational models (not JSON), so prices/ratings stay properly typed and a trip can have multiple flight legs (connections) as ordered rows. `Feedback` has a DB-level constraint requiring at least a destination or a trip.
  - `TripItem` (generic) and community-intelligence entities (`CommunityReview`, etc.) explicitly deferred to later milestones/phases, per `04_DATABASE_DESIGN.md`'s "avoid speculative entities."
  - Migrations validated end-to-end in Docker (`makemigrations` → `migrate` → `pytest` — 9 passing model tests — → `ruff check .` clean). The curated dataset was loaded for real (18/18 destinations).
  - **Note:** validating this required dropping and recreating the local dev Postgres volume (`docker compose down -v`), since `AUTH_USER_MODEL` can't change after migrations have been applied against it. The old volume only held the empty Milestone 1 smoke-test state — no real data was lost.
- [x] **Phase 5 — Authentication** ✅ Done 2026-08-29. Django's built-in auth system (session-based, per `07_API_DESIGN.md` §3 — no JWT/separate auth API), adapted for email login:
  - `users:register` — custom `UserRegistrationForm` (email + password), auto-logs in on success.
  - `users:login` / `users:logout` — Django's built-in `LoginView`/`LogoutView`, working out of the box with the custom email `USERNAME_FIELD` (no custom form code needed).
  - `users:account` — minimal `@login_required` page (Milestone 2 DoD's "authenticated area"), shows email + join date.
  - `LOGIN_URL`/`LOGIN_REDIRECT_URL`/`LOGOUT_REDIRECT_URL` configured; unauthenticated access to `account` redirects to login with `?next=`.
  - Google OAuth remains explicitly deferred (not implemented) — the user only asked for the door to stay open for it later.
  - 7 new tests (registration, login success/failure, logout, login-required redirect) — 16/16 total passing. Verified live in a real browser (register → auto-login → account → logout → login → account) in addition to automated tests. `ruff check .` clean, no new migrations needed.
- [x] **Phase 7 — First travel data integration** ✅ Done 2026-08-29 (done ahead of Phase 6, per explicit user request). New `integrations` app (no models, pure Python + one Django app registration):
  - `integrations.climate.ClimateProvider` — internal Travel Data Interface (`10_EXTERNAL_INTEGRATIONS.md` §3), an ABC with `get_monthly_climate(latitude, longitude, month, year=None) -> MonthlyClimateSummary`.
  - `integrations.climate.open_meteo.OpenMeteoClimateProvider` — the Phase 3-decided adapter, calling Open-Meteo's free Historical Weather (archive) API. Validated, normalized (averages daily highs/lows/precipitation), timeout (5s), and provider errors wrapped in `ClimateProviderError` rather than leaking raw provider details.
  - `integrations.climate.get_climate_provider()` — factory reading `settings.CLIMATE_PROVIDER` (default `"open_meteo"`), so swapping providers is a settings change, not an app-code change.
  - Redis-backed caching (7-day TTL — historical data for a past month doesn't change) per `10_EXTERNAL_INTEGRATIONS.md` §7.
  - **Documented MVP simplification:** without an explicit `year`, the adapter uses the most recently completed occurrence of the requested month as a stand-in for "typical" conditions — not a genuine multi-year climatological average. Noted as a natural future improvement, not a current requirement.
  - 7 new tests (mocked HTTP — success/cache-hit/network-failure/malformed-response/factory), all passing. **Also smoke-tested against the real Open-Meteo API** (not mocked): Lisbon in October 2025 → 24.8°C avg high, 17.1°C avg low, 48.6mm precipitation — consistent with the curated dataset's "best season Mar-Oct" for Lisbon.
  - Added `requests` to `requirements/base.txt`.
- [x] **Phase 6 — Traveler profile (edit/retrieve, authorization)** ✅ Done 2026-08-29 (out of order, after Phase 7, per user request). Reuses the `TravelerProfile` model from Phase 4 — kept intentionally minimal per `14_MVP_IMPLEMENTATION_PLAN.md` Milestone 6 ("do not create a large questionnaire unnecessarily... grow organically").
  - `users:profile` — `@login_required` view, always operates on `request.user`'s own profile (never accepts a profile id from the URL, so cross-user access isn't possible by construction), `get_or_create`s the profile on first visit.
  - `TravelerProfileForm` — `preferred_trip_types` rendered as checkboxes (`CheckboxSelectMultiple`) instead of a raw JSON textarea; `preferred_cost_of_living` as a normal select.
  - Linked from the account page ("Edit my traveler profile").
  - **Note on Milestone 6's full DoD** ("TravelAgent can use authorized profile information to personalize recommendations"): only the edit/retrieve/authorization half is done here — the recommendation engine that would consume this data doesn't exist yet (Phase 8). Expected at this point in the sequence, not a gap specific to this phase.
  - 4 new tests (login-required redirect, auto-create on first visit, save persists correctly, one user's edits don't affect another's) — 27/27 total passing. `ruff check .` clean, no new migrations. Verified live in a browser: checked "Beach" + "Culture", selected "Medium" cost tier, saved, confirmed success message and correct DB persistence.
- [x] **OpenAI adapter (Phase 2's remaining deliverable / Milestone 4 — AI Foundation)** ✅ Done 2026-08-29. New `ai` app (no models, same style as `integrations`):
  - `ai.provider.AIProvider` — internal AI Provider Abstraction (`05_AI_DESIGN.md` §10, `09_AI_ORCHESTRATION.md` §11), ABC with `generate_reply(messages, max_tokens=None) -> AIResponse`. `AIMessage`/`AIResponse` are plain dataclasses so the interface stays provider-agnostic.
  - `ai.provider.openai_provider.OpenAIProvider` — calls OpenAI's Chat Completions API. Validates/normalizes the response, wraps `OpenAIError`/empty-content/malformed-response cases in `AIProviderError`, defaults `max_tokens=600` for cost containment, raises a friendly `ImproperlyConfigured` (pointing at `.env.example`) if `OPENAI_API_KEY` is blank rather than a cryptic SDK error.
  - `ai.provider.get_ai_provider()` — factory reading `settings.AI_PROVIDER` (default `"openai"`), same swappable-via-settings pattern as the climate provider.
  - `ai/prompts.py` — the `SYSTEM_PROMPT` constant naming the assistant "Lunna" (per the Phase 2 decision) and encoding two product rules: travel-only scope (`09_AI_ORCHESTRATION.md` §10) and never inventing travel data (`05_AI_DESIGN.md` §7). Not auto-injected by the adapter — callers (the future orchestration layer, Phase 9) prepend it explicitly.
  - **Explicitly not built here:** the actual orchestrator that constructs context from `TravelerProfile`/`Destination`/conversation history, summarization, and response caching — those are Phase 9 (AI orchestration) concerns. This phase only delivers the swappable provider adapter itself, matching Milestone 4's scope.
  - Added `openai` to `requirements/base.txt`; `OPENAI_API_KEY`/`AI_MODEL` documented in `.env.example` (key left blank — real value is the user's to provide, never committed).
  - 6 new tests, all mocking the OpenAI client (no real API calls, unlike the free Open-Meteo adapter — a real call costs money on the user's account and needs a real key we don't have). 33/33 total tests passing, `ruff check .` clean, no new migrations. Manually confirmed the missing-key path raises the intended friendly error.
- [x] **Phase 8 — First recommendation algorithm** ✅ Done 2026-08-29. New `recommendations` app (no models — pure Python, mirroring `integrations`/`ai`), scoped strictly to `05_AI_DESIGN.md` §2/§5/§6 and Milestone 5's "Recommendation Logic" (Candidate Destination → Hard Constraints → Basic Score → Ranking). **Natural-language intent extraction and AI explanation are explicitly NOT part of this** — that's Phase 9.
  - `recommendations.scoring.RecommendationRequest` — already-extracted, deterministic constraints (`month`, `min_temp_c`/`max_temp_c`, `max_cost_of_living`, `excluded_slugs`, optional `user`).
  - `recommendations.scoring.generate_recommendations()` — queries `Destination`, fetches live climate via `integrations.climate.get_climate_provider()` (injectable for tests), applies hard constraints (temperature range, cost ceiling, exclusions), then scores survivors on: preference fit (matches `TravelerProfile.preferred_trip_types`), budget fit (headroom under the cost ceiling), temperature fit (margin above the minimum), and a repetition penalty (soft, not a hard exclusion) for destinations with a `completed` `Trip` — per `05_AI_DESIGN.md` §5's "previously visited... lower priority, not excluded". A destination the climate provider can't return data for is skipped gracefully (`10_EXTERNAL_INTEGRATIONS.md` §5), not a hard failure.
  - Community/feedback-based scoring terms from `05_AI_DESIGN.md` §6's full formula are **deliberately not included yet** — those belong to their own later milestones (Community Intelligence, Feedback & Learning) requiring aggregation/privacy safeguards this phase doesn't build.
  - 8 new tests, all with an injected stub climate provider (no network calls) — hard constraints, exclusions, ranking order, preference/repetition scoring, graceful degradation, and anonymous-user behavior. 41/41 total tests passing, `ruff check .` clean, no new migrations.
  - **Also validated against real, live data**: loaded the 18 curated destinations and ran `generate_recommendations(RecommendationRequest(month=10, min_temp_c=20.0, max_cost_of_living=3))` with the real Open-Meteo provider — returned a plausible, correctly-ranked list (Marrakech and Chiang Mai topped it: cheapest and genuinely warmest in real October climate data).
- [x] **Phase 9 — AI orchestration** ✅ Done 2026-08-29. `ai.orchestration.get_travel_recommendation(message, user=None)` - a stateless, single-message orchestrator per `09_AI_ORCHESTRATION.md` §3's pipeline (Intent Understanding → Travel Data/Rules → Recommendation Scoring → AI Reasoning). **Explicitly not built**: conversation history/persistence and streaming - both need the chat interface (Phase 10) to exist first.
  - Extended `AIProvider` with `generate_structured_reply(messages, json_schema)` - a generic structured-output method any provider adapter must support, not an OpenAI-only escape hatch, keeping the provider abstraction real. `OpenAIProvider` implements it via `response_format={"type": "json_schema", ...}`.
  - **Intent extraction**: first AI call, structured JSON output (`is_travel_request`, `needs_clarification`, `clarification_question`, `month`, `min_temp_c`, `max_cost_of_living`). The model is instructed to never guess a missing month — it asks a clarification question instead. Python-side validation double-checks the extracted values regardless of the schema (`09_AI_ORCHESTRATION.md` §9 — never fully trust model output).
  - **Scoring**: unchanged call into Phase 8's `recommendations.scoring.generate_recommendations()`.
  - **Explanation**: second AI call (plain text, not structured), prompted with only the top 5 already-ranked candidates and an explicit "do not invent any other destinations or facts" instruction — grounds the explanation in real, deterministic data.
  - Three short-circuit paths that skip the (paid) explanation call entirely: off-topic message, needs-clarification, and no-matches — each returns a canned/direct reply instead.
  - Any `AIProviderError` anywhere in the pipeline is caught and replaced with one generic fallback reply (deliberately simple — no partial-result salvage logic yet).
  - 8 new tests (6 orchestration + 2 for the new `generate_structured_reply` method), all using stub AI/climate providers — no network calls. 49/49 total tests passing, `ruff check .` clean, no new migrations.
  - **Update 2026-08-29 (same day):** the user provided a real `OPENAI_API_KEY`, now set in `.env` (never committed — `.env` is gitignored). A minimal live call confirmed the key works. A full live run of `get_travel_recommendation("I want somewhere warm in October, not too expensive")` surfaced a real bug: the "never guess a number" instruction was *too* conservative — qualitative words like "warm"/"not too expensive" came back with `min_temp_c`/`max_cost_of_living` as `null`, so the hard-constraint/scoring layer never actually engaged (all 18 destinations tied at score 0) and the second AI call ended up doing the real filtering itself from raw, unranked data — not the intended "AI reasons over already-scored candidates" design. **Fixed** by adding explicit interpretation anchors to `INTENT_EXTRACTION_SYSTEM_PROMPT` (e.g., "warm" → `min_temp_c=22`, "not too expensive" → `max_cost_of_living=3`) — this is the AI *interpreting the user's own words* into an operational threshold, not inventing a destination fact, so it doesn't violate the anti-hallucination rule. Re-ran live after the fix: correctly narrowed to 8 destinations with differentiated scores, top result (Marrakech/Chiang Mai) matching Phase 8's pure-scoring test exactly. This refinement is validated by live testing, not a unit test — prompt-interpretation quality isn't meaningfully mockable.
- [x] **Phase 10 — Chat interface** ✅ Done 2026-08-29. Django templates + a small amount of JS (no React, per the docs). This is Milestone 5's "First Vertical Slice" checkpoint — a person can now actually talk to Lunna through a browser.
  - `GET /chat/` — the chat page (`ai/templates/ai/chat.html`), open to anonymous users (registered users get personalization for free since the view passes `request.user` through when authenticated).
  - `POST /api/v1/recommendations/` — matches the path already sketched in `07_API_DESIGN.md` §8. Returns a real `StreamingHttpResponse` (`text/plain`) of the reply text, built on `ai.orchestration.stream_travel_recommendation()` (extended in this phase from the Phase 9 pipeline — see below).
  - Client-side JS (`fetch` + `ReadableStream`, no framework): appends the user's message immediately, shows a "Lunna is thinking..." bubble, replaces it with the incrementally-arriving reply, handles network failure and non-200 responses with a visible error bubble, and disables the input while a request is in flight (loading state).
  - Request Validation added at the view (empty or >2000-char messages rejected with 400 before any AI call is made) — the pipeline step named in `09_AI_ORCHESTRATION.md` §3 that hadn't been implemented anywhere yet.
  - **Explicitly deferred:** true multi-turn conversation memory. Each message the user sends is still processed independently by the orchestrator; the page only keeps a growing visual thread for the current browser visit, it doesn't feed earlier turns back into context. Real conversation memory is future work, not assumed to exist yet.
  - **Orchestrator extended for real streaming**: added `AIProvider.stream_reply()` to the interface (any provider must support it) and `OpenAIProvider`'s implementation via the SDK's `stream=True`. Rebuilt `ai.orchestration` around a new `stream_travel_recommendation()` as the core pipeline (mirrors the old `get_travel_recommendation()` exactly, but yields the explanation incrementally); `get_travel_recommendation()` is now a thin wrapper that joins the chunks, kept for tests/simple callers.
  - 12 new tests (3 for `stream_reply`, 3 for the streaming orchestrator path, 6 for the views) — 61/61 total passing, `ruff check .` clean, no new migrations.
  - **Real, live browser validation** (not just mocked tests): loaded `/chat/` with the real OpenAI key, sent "somewhere warm in October, not too expensive" — got the same Marrakech/Chiang Mai/Hoi An answer as the shell tests, streamed incrementally into the page. Also verified live: the off-topic scope guard ("what's the capital of France?"), the clarification path ("somewhere warm and cheap" with no month → Lunna asked which month), and that both exchanges correctly accumulate in the on-page thread.
  - **Real bug found and fixed during this live testing**: `templates/base.html` was missing `<meta name="viewport">` entirely (true since Phase 1, not just this page). On a mobile-emulated viewport, `window.innerHeight` came back as 2123 instead of 812, so the chat page's `height: 100vh` container rendered nearly 3 screens tall with the input pushed far below the fold. Added the standard `width=device-width, initial-scale=1` viewport meta tag to `base.html` (fixes it site-wide, not just for chat) and reconfirmed `innerHeight` correctly reports 812 with the input properly pinned to the bottom of one screen.
- [~] **Phase 11 — First End-to-End MVP (Joint Review)** ⚠️ In progress 2026-08-29. Ran all 7 real scenarios named in `15_IMPLEMENTATION_GUIDE.md` (warm, budget, romantic, beach holiday, city break, family travel, strong exclusions) live against the real OpenAI API + real climate data. Findings:
  - ✅ **Warm / budget destination** — worked correctly out of the box.
  - ❌ **Found & fixed same day:** beach holiday, city break, and exclusions ("please not X") had **zero effect** on the deterministic `recommendations` list — `RecommendationRequest` had no `trip_type` field, and there was no path from natural language to `excluded_slugs` at all. Confirmed concretely: asking to exclude Chiang Mai still returned it ranked #2. Fixed:
    - `recommendations.scoring.RecommendationRequest` gained a `trip_type` hard constraint (matches `Destination.trip_type`).
    - `travel.services.find_destination_slugs_by_name()` (new) resolves free-text place/country names (case-insensitive, matches name or country) into slugs.
    - `ai.orchestration`'s intent schema gained `trip_type` (enum: beach/city/nature/culture/null — the model is explicitly told not to force-fit "romantic"/"family" into one of these) and `excluded_place_names` (array), both validated defensively like the existing fields.
    - Re-verified live: beach holiday → 3/18 correctly beach-only; city break → 5/18 correctly city-only; Chiang Mai exclusion → genuinely absent from the data now, not just coincidentally omitted from the AI's text.
    - 10 new tests (trip_type hard constraint, `find_destination_slugs_by_name` unit tests, orchestrator-level trip_type/exclusion tests) — 71/71 total passing, `ruff check .` clean, no new migrations.
  - ✅ **Recommendation philosophy decided 2026-08-29 (human decision):** for requests with no deterministic model (e.g. "romantic", "family-friendly"), the AI answers from its own general knowledge rather than the app trying to predict every possible category in advance — this is intentional, not a gap to keep closing. What the app does do is **log** these cases (and genuine failures) for future review, so real usage — not guesswork — informs which dimensions eventually get formalized. Implemented as structured logging in `ai.orchestration` (Python `logging`, not a new DB model — that's premature before a real analytics need, per `15_IMPLEMENTATION_GUIDE.md`'s general philosophy):
    - INFO when a valid travel request extracts no deterministic constraints at all (trip_type/min_temp_c/max_cost_of_living all null) — "relying on AI judgment."
    - INFO when hard constraints eliminate every candidate (no matches).
    - WARNING when an `AIProviderError` occurs (intent extraction or mid-stream) — a genuine failure, not a philosophy choice.
    - 3 new tests using Django's `assertLogs`; 74/74 total passing, `ruff check .` clean. Confirmed live: a real "romantic getaway" request logged exactly the intended line.
  - Still open, not addressed by this decision: in a couple of replies during testing the AI added supplementary facts not present in our dataset (e.g. "Lisbon has nearby beaches," "Kyoto is known for safety") — a grounding concern, separate from the recommendation-philosophy question.
  - **✅ Human Decision made 2026-08-29: "yes, continue expanding."** Phase 11 is closed.
- [x] **Phase 12 — Travel History** ✅ Done 2026-08-29. Per `04_DATABASE_DESIGN.md` §2/§4, Travel History is a distinct entity from `Trip` (a much simpler standalone record — "visited X, roughly year Y" — not a full itinerary with items). Note: the existing `Trip.status="completed"` repetition-penalty logic from Phase 8 was real code but practically unreachable by any user until now, since there's still no Trip-creation UI (that's Phase 13).
  - `trips.TravelHistoryEntry` (new model): `user`, `destination`, `visited_year` (nullable — "approximate... where useful").
  - Full CRUD at `/trips/history/` (`login_required`; structural authorization — every view scopes to `user=request.user`, confirmed via tests that another user's entries 404 rather than leak or allow editing).
  - `recommendations.scoring._visited_destination_slugs()` now unions completed `Trip`s **and** `TravelHistoryEntry` records — either counts as "visited" for the soft repetition penalty (not a hard exclusion, per the "important rule" in both `05_AI_DESIGN.md` §5 and this phase's own framing).
  - Linked from the account page ("My travel history").
  - 10 new tests (model, 7 view/authorization cases, repetition-penalty-from-history) — 83/83 total passing, `ruff check .` clean. One new migration (`trips.0003_travelhistoryentry`).
  - **Verified live, including the actual scoring effect**: added "Chiang Mai, 2019" via the real browser UI for a real logged-in user, then confirmed via `get_travel_recommendation(..., user=that_user)` against the real OpenAI + Open-Meteo APIs that Chiang Mai's `repetition_penalty` became `3.0` and it dropped from top-ranked to 5th place — present, just deprioritized, exactly as intended.
- [x] **Phase 13 — Trip Management** ✅ Done 2026-08-29. Per `15_IMPLEMENTATION_GUIDE.md` Phase 13 / `14_MVP_IMPLEMENTATION_PLAN.md` Milestone 8: create/edit/view/delete a `Trip` (name, destination, dates), plus "save relevant recommendations." **Do not build advanced itinerary management** — respected; no new Trip Item types added.
  - `Trip` gained a `name` field (nickname, e.g. "Summer in Lisbon"; blank falls back to `"{destination}"` in `__str__`/display). Migration `trips.0004_trip_name`.
  - Full CRUD at `/trips/` (list), `/trips/create/`, `/trips/<pk>/` (detail), `/trips/<pk>/edit/`, `/trips/<pk>/delete/` — all `login_required`, structurally scoped to `user=request.user` (another user's trip 404s, matching the established pattern).
  - **"Save relevant recommendations" implemented for real**, not skipped as a stretch goal: `/api/v1/recommendations/`'s streaming response now appends a trailing delimiter + JSON footer (`[{slug, name, country}, ...]` for the top recommended destinations) after the visible reply text. The chat page's JS buffers the stream, strips the footer out of the displayed bubble text, parses it, and renders a "Save as trip" link per destination pointing at `/trips/create/?destination=<slug>` (which pre-fills that destination in the create form).
  - Linked from the account page ("My trips").
  - 16 new tests (Trip CRUD + authorization, prefill-from-query-param, and the recommendations-footer behavior on the streaming view) — 93/93 total passing, `ruff check .` clean.
  - **Verified the full real, live flow end-to-end**: asked Lunna for a real recommendation in the browser → got 5 "Save as trip" links with clean (non-leaked) reply text → clicked "Save Marrakech as a trip" → form opened with Marrakech pre-selected → saved as "October trip" → landed on the trip detail page → confirmed it appears in the trip list.
- [ ] Phase 14 onward — see `15_IMPLEMENTATION_GUIDE.md` for the full phase list (Phase 14 — Feedback)

## What exists in the repo right now

```
TravelAgent/
├── .github/workflows/ci.yml       CI: lint (ruff) + tests, against real Postgres+Redis
├── config/                        Django project (settings split by environment, urls, wsgi/asgi, celery.py)
├── core/                          Infra-only app: GET /health/ (checks DB connectivity) + test
├── documentation/                 Architecture docs (01–15) + this tracking set
│   └── data/curated_destinations.json   Approved initial destination dataset (Phase 3, 18 entries)
├── users/                         Custom User (email login) + TravelerProfile
├── travel/                        Destination model + `load_destinations` management command
├── trips/                         Trip (+ CRUD at /trips/), TripFlight, TripAccommodation, Feedback, TravelHistoryEntry (+ CRUD at /trips/history/)
├── integrations/                  climate/ - ClimateProvider interface + Open-Meteo adapter (no models)
├── ai/                             provider/ (incl. streaming) + orchestration.py + prompts.py (Lunna); views.py/urls.py/templates - the /chat/ page (no models)
├── recommendations/                scoring.py - deterministic recommendation scoring/ranking (no models)
├── requirements/                  base.txt / development.txt / production.txt
├── docker-compose.yml             db (Postgres 16) + redis (7) + web + worker (celery)
├── Dockerfile                     multi-stage (builder installs deps, runtime stays slim)
├── .env.example                   template for local .env (never commit real .env)
├── manage.py, pyproject.toml (ruff+pytest config), .gitignore, .dockerignore, README.md
```

`users`, `travel`, and `trips` now exist (Phase 4, 2026-08-29). `recommendations`, `ai`, and `integrations` still don't — deliberately, until the phases that need them (AI orchestration, provider adapters) are reached. See `DEVELOPMENT_LOG.md`.

## Known environment gaps (not decisions — just missing local tooling)

- **Docker Desktop is installed and its engine works** (validated 2026-08-28 — see resolved section above). Virtualization is enabled; WSL2 backend starts cleanly.
- **A PostgreSQL 18 server is also installed and running as a Windows service** (`postgresql-x64-18`, listening on `0.0.0.0:5432`) — pre-existing system state, not created for TravelAgent, unrelated to TravelAgent's Dockerized Postgres 16. Claude Code does not have its credentials and has not touched it. Note: Docker Compose's `db` service also publishes host port 5432 and bound successfully during validation — the two do not appear to conflict in practice (likely because they're not both listening at the same time), but avoid running both simultaneously if port-binding errors ever appear.
- Local Python available via the `py` launcher (3.14). A `.venv` exists at the repo root with dependencies installed; `python manage.py check` and `ruff check .` both pass outside Docker too.
- The Docker image pins Python 3.12 (more predictable wheel availability for `psycopg`) — confirmed working (3.12.14 inside the built image).
- Local `.env` now exists (gitignored) with a generated `DJANGO_SECRET_KEY`, copied from `.env.example`. Future sessions on this machine don't need to recreate it — it also has a real `OPENAI_API_KEY` as of Phase 9's live-testing session (2026-08-29).
- **GitHub remote configured** (2026-08-29): `origin` → `https://github.com/wanderes-dev/wanderes.git`, branch `master` pushed and tracking `origin/master`. Push authentication goes through Windows Git Credential Manager — the cached credential is for the `wanderes-dev` GitHub account (a different, earlier-cached `cantarino10` credential was rejected since it didn't have access to this repo). If push auth ever fails again with "Repository not found," check which GitHub account GCM is using (`git credential fill` with `protocol=https`/`host=github.com`) before assuming the repo itself is missing.

## Next actionable steps

Per `15_IMPLEMENTATION_GUIDE.md`'s phase list, the next unstarted phase is **Phase 14 — Feedback** (owner: Claude Code + Human Review). See the phase-by-phase checklist above for everything already done.

## Resume checklist for a fresh Claude session

If you're picking this up cold:

1. Read this file first.
2. Read `DECISIONS_PENDING.md` to see if the human has since made a decision (if so, update this file and proceed to the corresponding phase).
3. Read `DEVELOPMENT_LOG.md` for full historical context on what was built and why.
4. Do **not** re-implement Phase 0/1 — it's done and fully validated in Docker. Do **not** jump ahead to Phase 4+ without confirming Phase 2/3 decisions are actually resolved.
5. If Phase 2/3 are still unresolved, the only useful next step is asking the user for those decisions (see `DECISIONS_PENDING.md`) — do not guess AI/travel-data providers.
