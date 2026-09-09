# 16 — Analytics & Data Engineering Architecture

> Written 2026-09-09, as part of the analytics/data-engineering evolution described in `DEVELOPMENT_LOG.md`'s corresponding entry. This document is the durable reference — read it before touching anything under `analytics/`, and update it whenever the shape of this system changes (a new event, a new view, a new mart, a changed metric definition).

## 1. Why this exists

Wanderes had a minimal, deliberately-scoped self-hosted analytics app since Phase 17 (2026-08-30): one `Event` table, 9 instrumented call sites, library-only metric functions, a read-only Django admin as the "dashboard." That was the right call at the time — it answered "is anyone using this at all" without over-building ahead of real need. It could not answer the questions that actually matter for operating Wanderes today: *are people reaching recommendations, where do they abandon the flow, which destinations get saved vs. ignored, is the AI layer reliable, what's response latency, are failures increasing.* This document describes the system built to answer those questions, and the reasoning behind every non-obvious choice in it.

**Explicit non-goal:** this is not a portfolio exercise. Every technology decision below was made against Wanderes's actual current scale (pre-launch, effectively zero production traffic) and actual current codebase (Django + Postgres + Redis + Celery, nothing else), not against what would look most sophisticated. Where a heavier tool was considered and rejected (dbt, Airflow, a separate analytics database, Sentry/APM), the rejection is recorded with a concrete condition under which the decision should be revisited — not a blanket "no forever."

## 2. Architecture overview

```
Product events (chat, registration, trips, feedback)
Operational events (AI calls, provider calls)
                    │
                    ▼
        analytics.Event  (raw layer — one append-only Postgres table)
                    │
                    ▼
   analytics/warehouse/sql/*.sql  (transformation layer — Postgres VIEWs,
   version-controlled, documented, tested; no new tooling, no ETL job)
                    │
        ┌───────────┼──────────────────────────┐
        ▼           ▼                          ▼
  dim_destinations  int_event_episodes ──▶ fact_conversations
  dim_users               │           └─▶ fact_recommendations
                           ▼
                     fact_ai_requests
                     fact_feedback (sources trips.Feedback directly)
                    │
                    ▼
   analytics.tasks.refresh_daily_metrics  (Celery Beat, nightly)
                    │
                    ▼
   analytics.models.DailyProductMetrics  (the one MATERIALIZED table —
   a real Postgres table, not a view, refreshed by full recompute-and-
   upsert each night)
                    │
                    ▼
   /analytics/dashboard/  (staff-only, server-rendered Django view)
```

Everything left of the dashboard is queryable directly — via the Django ORM (`analytics.warehouse.models`), via `psql`, or by any future BI tool pointed at the same Postgres instance. A view has no state of its own beyond its query, so every consumer sees the same data.

## 3. Event taxonomy

### 3.1 Existing events (Phase 17, unchanged)

| Event | Fires | Notes |
|---|---|---|
| `user_registered` | Manual registration success, or Google OAuth first signup | Two call sites, deduplicated by construction (allauth's signal never fires from the manual path) |
| `profile_completed` | First time a `TravelerProfile` gets real content | Guarded to fire once |
| `travel_question_submitted` | Any chat POST, regardless of outcome | The base "engagement" signal |
| `recommendation_generated` | A recommendation pipeline run returns ≥1 destination | Enriched 2026-09-09, see below |
| `trip_created` | A `Trip` is saved, chat or form | Enriched 2026-09-09, see below |
| `feedback_submitted` | `Feedback` is saved, chat or form | |

### 3.2 New events (2026-09-09)

| Event | Fires | Actor | Why |
|---|---|---|---|
| `destination_selected` | "Choose this trip" clicked (`focus_destination_slug` → `is_destination_detail` result) | user or anonymized IP | Shipped 2026-09-08, had zero instrumentation until now — a real, deliberate user action distinct from a passive recommendation being generated |
| `signup_started` | GET `/users/register/` | anonymized IP (always anonymous by construction) | Pairs with `user_registered` for a real signup funnel, especially now that the save-trip flow routes people here contextually |
| `anonymous_user_authenticated` | Manual login of an **existing** account, when the visitor had a pre-login session | user | The other half of "anonymous → authenticated conversion" that `user_registered` alone can't answer (that only covers new signups) |
| `llm_request_completed` | One AI-provider call completes (success or failure) | **none** (operational) | Latency/reliability for the AI layer — see §7 |
| `provider_request_completed` | One external (non-AI) provider call completes | **none** (operational) | Same, for `integrations.climate` today, reusable for future flight/hotel providers |

`llm_request_completed`/`provider_request_completed` are deliberately **one event per completed attempt**, not a started/completed/failed triple — a synchronous call always either completes or fails 1:1 with its start, so a separate "started" event would carry no independent analytical value. This collapses the classic 3-event pattern into 2 event types total without losing any signal (success rate, latency, and failure counts are all derivable from one row per attempt).

### 3.3 Events considered and deliberately NOT built

- **`recommendation_viewed`** — reaffirms the original 2026-08-30 decision. There is no separate results page; a recommendation card renders inline in the same streamed response that generates it, so "generated" and "viewed" are the same server-side moment. Building this would be a fabricated distinction with no real signal behind it.
- **`recommendation_rejected`** — no reject/dismiss UI action exists in the product. Manufacturing an event for an action that doesn't exist would violate the "only implement events that make sense" principle. Rejection is instead a **derived metric**: a destination recommended but never selected/saved within the same conversation episode (see `fact_recommendations.was_selected`/`was_saved` — their negation is the rejection signal, computed at query time, not captured as a raw event).
- **`conversation_started`** — considered, then cut. It's fully derivable in the warehouse layer as the first `travel_question_submitted` timestamp of a conversation episode (see `fact_conversations.started_at`). Adding it as a raw event would be pure duplication.
- **`message_sent`** — the prompt's suggested taxonomy names this; it's already exactly what `travel_question_submitted` means (any chat interaction). Not duplicated under a second name.

## 4. Dimensions captured

Per event (on `analytics.Event`, all optional except `event_type`/`created_at`):

- `event_type`, `created_at` — always present.
- `user` (FK, `SET_NULL`) — set for authenticated events.
- `anonymized_ip` — set for anonymous, non-operational events (`/24` IPv4, `/48` IPv6 — see §8).
- `metadata` (JSONField) — small structured payload, e.g. `destination_slug`, `latency_ms`. Never free text.
- `conversation_key` (added 2026-09-09, indexed) — the exact string `ai.memory.conversation_key()` produces, letting chat-related events be joined together. **Not itself a per-conversation identifier** — see §5.1.
- `locale` (added 2026-09-09) — `request.LANGUAGE_CODE` when available, answering "which locales/markets are being used."

Destination identifiers travel as `destination_slug` in `metadata` (stable, locale-independent — confirmed via the 2026-09-04 i18n pass that `Destination.slug`/`.name`/`.country` are untouched by locale, only their *rendered* choice labels vary). There is **no `recommendation_id`** — see §5.3 for why.

## 5. Canonical models

Every view lives in its own file (`analytics/warehouse/sql/*.sql`), documented at the top of that file with grain/primary key/source/business meaning/update frequency. This section summarizes; the `.sql` files are the source of truth if the two ever drift.

### 5.1 `int_event_episodes` (intermediate — not for direct dashboard use)

**Grain:** one row per `analytics_event` with a non-null `conversation_key`.
**Primary key:** `event_id`.
**Source:** `analytics_event`.
**Why it exists:** `ai.memory.conversation_key()` returns the **same string for an authenticated user's entire lifetime of chat activity** (`chat-history:user:{pk}`) — correct for its real purpose (cross-device short-term memory continuity) but **not** a per-conversation identifier. This was the single most important correctness risk identified before implementation (flagged in the pre-implementation report, verified as a real bug during a validation pass that read the actual code). Naively using `conversation_key` as a join key would silently merge a retained user's entire chat history into one "conversation," corrupting every funnel/correlation metric for exactly the segment that matters most.

**The fix:** `episode_number`, computed via a standard SQL sessionization window function — a new episode starts whenever the gap since the previous event on the same `conversation_key` exceeds 30 minutes (the exact TTL `ai.memory`'s own Redis-backed state already uses, so this is the same "conversation" boundary the application itself already treats as real). Verified concretely: two events 40 minutes apart for the same authenticated user get different `episode_number`s; two events 10 minutes apart don't (both are automated tests, see `analytics/warehouse/tests/test_views.py::EpisodeSplittingTests`, and were manually confirmed against a live Postgres instance before the automated test was even written — see that test file's own module docstring for the `auto_now_add` gotcha hit along the way).

`fact_conversations` and `fact_recommendations` both build on this one view rather than duplicating the sessionization SQL.

### 5.2 `dim_destinations`

**Grain:** one row per `travel.Destination`. **PK:** `destination_id`. **Source:** `travel_destination` LEFT JOIN `travel_countryentryrequirement`. **Fields:** slug, name, country, trip_type, cost_of_living, `has_video` (derived from whether the country has any real videos on file). **Update frequency:** live.

### 5.3 `dim_users`

**Grain:** one row per `users.User`. **PK:** `user_id`. **Source:** `users_user` LEFT JOIN `users_travelerprofile`. **Fields:** date_joined, last_login, preferred_language, is_staff, home_country, preferred_cost_of_living, has_traveler_profile. Deliberately minimal — no email/name, even though this is an internal-only surface (data minimization on principle). **Update frequency:** live.

### 5.4 `fact_conversations`

**Grain:** `(conversation_key, episode_number)` — one row per real conversation episode. **PK:** `id` (an md5 hash of the grain, since Postgres views carry no real PK constraint and the Django unmanaged model needs one). **Source:** `int_event_episodes`. **Fields:** started_at, last_event_at, user_id, locale, message_count, reached_recommendation, reached_selection, reached_trip_created, reached_feedback. **Business meaning:** how far one conversation got — the basis for the conversation funnel. **Update frequency:** live.

### 5.5 `fact_recommendations`

**Grain:** `(conversation_key, episode_number, destination_slug)` — one recommended destination within one episode, unnested from `recommendation_generated.metadata.destination_slugs`. **PK:** `id` (md5 hash of the grain). **Source:** `int_event_episodes`. **Fields:** recommended_at, was_selected, was_saved.

**This is the model most worth understanding the tradeoffs of.** `was_selected`/`was_saved` are computed via a correlated `EXISTS` check against a later `destination_selected`/`trip_created` event sharing the same `conversation_key`, `episode_number`, and `destination_slug`. This is a **deliberate, approximate, session-based correlation — not a hard foreign key.** Minting a real `recommendation_id` and threading it through the "Choose this trip"/"Save this trip" UI (query params, a hidden field, a new column on `Trip`) would have been a materially larger, riskier change than this pass's value justified; the approximate correlation answers the same business question ("did this recommended destination lead to a positive outcome") with a small, honestly-documented margin of error. **Known edge cases, accepted:** a destination recommended twice in one episode and later selected can't be disambiguated between the two recommendation moments; an out-of-order or cross-episode action isn't captured. **Update frequency:** live.

### 5.6 `fact_ai_requests`

**Grain:** one row per `llm_request_completed`/`provider_request_completed` event. **PK:** `event_id`. **Source:** `analytics_event`. **Fields:** event_type, operation, success, latency_ms, error_type, conversation_key. **Deliberately no token/model/cost data** — see §7. **Update frequency:** live.

### 5.7 `fact_feedback`

**Grain:** one row per `trips.Feedback`. **PK:** `feedback_id`. **Source:** `trips_feedback` directly — **not** the analytics event log. This is a deliberate modeling choice worth stating explicitly: **not every fact should source from the event log.** `Feedback` already persists with strictly more fidelity (rating, tags, real FK relationships) than `feedback_submitted`'s thin metadata, so the operational table is the better source whenever the entity already lives somewhere durable. The event log is the right source only for genuinely ephemeral behavior that has no other home (a recommendation being generated, a destination being selected). Resolves `destination_id`/`destination_slug` via `trip.destination` when `Feedback.destination` is null (the table's own `feedback_has_destination_or_trip` CHECK constraint guarantees one is always set). Never exposes `Feedback.comment` (free text) — same principle `analytics.Event`'s own model docstring already states.

### 5.8 `analytics.models.DailyProductMetrics` (the one materialized table)

**Grain:** one row per calendar date. **PK:** `date`. **Source:** a parameterized query (`analytics/warehouse/sql/daily_product_metrics.sql`) over the views above, run once nightly by `analytics.tasks.refresh_daily_metrics`. **Why materialized, unlike everything else:** the dashboard queries this repeatedly, and its computation (scanning full event history grouped by day) gets slower as history grows — materializing at daily granularity keeps dashboard queries fast regardless of raw event volume, which none of the live views need since they're queried on-demand over a bounded recent window. **Freshness signal:** `computed_at` (auto-updated on every write) — if `MAX(computed_at)` is more than ~26 hours old, the nightly job has stalled. A realistic, checkable definition, not a fabricated enterprise SLA.

## 6. Data quality strategy

**Philosophy:** correctness over dashboard polish. Every view has automated tests that query the *real* views (not mocks), so a genuine SQL regression fails CI, not just a manual smoke test.

**What's tested** (`analytics/warehouse/tests/test_views.py`, `analytics/tests/test_tasks.py`, `analytics/tests/test_dashboard.py`):
- **Correctness of the sessionization fix** — the single highest-value test in this whole system (§5.1).
- **Correlation logic** — `was_selected`/`was_saved` computed correctly, including a negative case (a selection *before* the recommendation must not be misattributed).
- **`has_video` reflects real data**, including the "no `CountryEntryRequirement` row at all" edge case.
- **`fact_feedback` correctly resolves destination via trip** when `Feedback.destination` is null.
- **Operational events have no actor** (`fact_ai_requests` rows never carry `user`/`anonymized_ip`).
- **Latency is never negative** (a data-quality invariant, not just a happy-path check).
- **The mart is idempotent** — re-running `refresh_daily_metrics` for the same date doesn't double-count (`test_rerunning_for_the_same_date_does_not_double_count`).
- **Dashboard access control** — anonymous/non-staff users are redirected; staff users can view it.
- **Analytics failures never break the product** — `test_analytics_failure_does_not_break_the_recommendation_flow` monkeypatches `Event.objects.create` to raise and confirms the full chat pipeline still completes successfully. This property was already true and tested for the original 6 event types (2026-08-30); the same guarantee now explicitly covers all 11.

**What happens when a check fails:** in CI, the same as any other test failure — the change is blocked. In production, `record_event()`'s own contract (never raises, logs at WARNING and swallows) means a live data-quality problem degrades to "this event silently wasn't recorded," never to a broken user-facing request. This is a deliberate tradeoff: analytics availability is never allowed to couple to the core recommendation flow's availability, even at the cost of occasionally losing a data point.

**Freshness expectations, stated plainly:** the raw event layer and every view are live (no staleness possible — they're views, not copies). The one materialized table, `DailyProductMetrics`, is expected fresh within ~26 hours (one nightly run, one day of slack for weekday scheduling quirks). This is not a formal SLA with alerting — Wanderes doesn't have alerting infrastructure yet (see §12) — it's a documented, checkable expectation an operator can verify by looking at `computed_at`.

## 7. AI/provider instrumentation — exact scope, and why it stops where it does

`ai.provider.base.AIResponse` already carried `model`/`prompt_tokens`/`completion_tokens` fields before this pass, correctly populated by `OpenAIProvider.generate_reply`/`generate_structured_reply` — but every existing caller discarded everything except `.content`, and `stream_reply()` (the method that serves actual chat traffic via the sole shared `_stream_ai_reply()` helper) yields raw text chunks with **no** usage data at all, and never did.

This pass added `analytics.instrumentation.track_llm_call`/`track_provider_call` (small context managers, `analytics/instrumentation.py`) wrapping:
- `_extract_intent` and `_extract_climate_budget_signal` (both call `generate_structured_reply`, which returns a plain `dict`, not an `AIResponse` — no token/model data available here either, despite being non-streaming).
- `_stream_ai_reply()` itself — the one function that covers all 12 orchestration branches (recall/visa/booking/video/activity/off-topic/feedback/future-intent/explanation/focus-destination/etc.) for free, since it's the sole call site of `stream_reply`.
- `integrations.climate.open_meteo.OpenMeteoClimateProvider._fetch()` — deliberately **not** the public `get_monthly_climate()` entry point, which is called up to ~384 times per chat message (once per surviving candidate) and ~4,600 times per 3-day cache-warming run; almost all of those are cache hits. `_fetch()` only runs on an actual cache miss, which is what "a provider request" honestly means.

**Net result: this pass captures latency + success/failure + a coarse `error_type` (exception class name only, never a message or stack trace) — and nothing else.** No token counts, no model name, no cost. This is a real, honest limitation, not an oversight:
- `ai.conversations._generate_subject` is the one call site in the whole codebase that *would* get free token/model data (it uses `generate_reply`, which returns a real `AIResponse`) — deliberately left uninstrumented this pass: it fires once per new saved conversation, low volume, low value relative to the three call sites above.
- Extending `AIProvider.stream_reply`'s contract to also expose usage data (e.g. requesting OpenAI's `stream_options={"include_usage": True}` and yielding a final usage record) would unlock real per-request cost tracking for the traffic that actually matters — but it's a genuine interface change to the core AI abstraction, touched by roughly 104 existing orchestration tests. Not attempted this pass; **this is the documented path to real AI cost metrics**, and the right next step once cost visibility becomes a real operational need (see §12).

## 8. Privacy decisions

Extends, rather than revisits, the Phase 17 privacy decisions already on record (`DECISIONS_PENDING.md` §3):
- IP anonymization unchanged (`/24` IPv4, `/48` IPv6, never the raw address stored).
- `metadata` stays small and structured — destination slugs, ratings, latency numbers, exception class names. Never free text (`Feedback.comment` stays only on `trips.Feedback`, deliberately never duplicated into an event, same principle as before).
- `conversation_key`/`locale` are the two new dimensions on `Event`. Neither is more identifying than what was already stored: `conversation_key` is either an internal user PK (already linkable via the `user` FK) or a Django session key (already the same identifier `ai.memory`'s existing Redis state uses) — no new PII surface.
- **Operational events (`llm_request_completed`/`provider_request_completed`) carry no actor at all** — no `user`, no `anonymized_ip`. This is stricter than every other event type, not looser: these describe the AI/provider *system's* behavior, not a specific visitor's.
- `dim_users` (internal-only, staff-gated) exposes `home_country`/`preferred_language`/tenure fields — never email, name, or password. Minimized on principle even though nothing external can reach it.
- The dashboard is `@staff_member_required` and disallowed in `robots.txt` from day one (unlike `/travel/`'s staff tool, which was reactively fixed after already shipping crawlable — done right the first time here specifically because that earlier mistake is on record).

## 9. Orchestration strategy: why Celery Beat, not Airflow

Wanderes has exactly one new scheduled job from this pass (`refresh_daily_metrics`, nightly). Celery + Beat are already running in production, already proven with two other tasks (`warm_climate_cache`, `update_traveler_preferences_from_feedback`), and the worker already embeds Beat via `-B` (a documented, accepted constraint: correct only with exactly one worker instance, already true and already relied on by the existing task).

**Dependencies/execution order:** `refresh_daily_metrics` depends on all raw `Event`/`Feedback`/`Trip` data for its target date being complete. It always computes `today - 1 day` (UTC), never today, specifically to avoid a partial-day race against events still arriving.

**Retry behavior — a deliberate asymmetry from the existing tasks:** `record_event()` itself (the per-request, synchronous write) never retries and never raises — a transient failure there should degrade silently rather than risk blocking a user-facing request. `refresh_daily_metrics`, by contrast, **does** configure `autoretry_for`/`retry_backoff` (unlike either pre-existing Celery task) — it's a scheduled batch job, not a synchronous request-path write, so a transient DB blip should retry rather than silently skip a whole day's numbers. Both choices are correct for their own context; this document exists partly so a future session doesn't "fix" one to match the other without understanding why they differ.

**Idempotency:** full recompute-and-upsert (`update_or_create` keyed by date) every run — the same "recompute from scratch, never incremental counters" pattern already proven by `update_traveler_preferences_from_feedback`. A retried or manually re-run refresh for the same date can never double-count (verified by `test_rerunning_for_the_same_date_does_not_double_count`).

**Failure handling/observability:** no Sentry/APM exists in this codebase (confirmed by direct inspection before this pass — plain Python logging only). A failed refresh surfaces via Celery's own worker logs (visible in Render's log stream) and, more durably, via the `computed_at` staleness check (§6). This is intentionally not a fabricated enterprise monitoring setup — see §12 for when that becomes worth building.

**Why not Airflow:** one job, running on infrastructure that already exists and already works, does not justify a second orchestration system. Revisit only if the number of interdependent scheduled jobs grows enough that Celery Beat's flat, un-DAG'd scheduling genuinely becomes the bottleneck — not before.

## 10. Why not dbt (yet)

Explicitly raised as a question in the original task, so the reasoning is recorded here, not just implied by its absence.

dbt's real value — enforced testing/documentation discipline across *many* models and *multiple* contributors, incremental materialization that matters at *real* data volume — doesn't apply yet. Wanderes today is solo-maintained, pre-launch, with a small (7 view + 1 materialized table) and stable transformation graph, fully expressible as tested SQL views using tooling already in the stack (Postgres, Django, pytest). Introducing dbt now would mean a second query paradigm (Jinja-templated SQL), a new deploy artifact (`dbt run` needs to run somewhere — a new Celery task wrapping the CLI, new credentials wiring, a `target/`/`manifest.json` build state), for zero data-volume benefit today.

**What was built instead, deliberately shaped to mirror dbt's own conventions** so a future migration is a mechanical exercise, not a rewrite: one `.sql` file per model, each self-documenting its grain/PK/source/business meaning at the top (dbt's own model-file idiom, without dbt's toolchain); a `staging → intermediate → marts`-shaped layering (`int_event_episodes` as the one intermediate; `dim_*`/`fact_*` as marts-equivalent); generic data-quality tests expressed in the project's existing test framework instead of dbt's YAML `tests:` block.

**Concrete conditions to revisit this decision** (not "someday," but specific and checkable):
- The view count exceeds ~15 (currently 7 — room to roughly double before this becomes unwieldy by hand).
- The same transformation logic starts getting hand-duplicated in more than one place (the `int_event_episodes` intermediate view exists specifically to avoid this happening for sessionization — a similar duplication pressure elsewhere is the signal to revisit).
- A second person needs to write and reason about independent transformations against this data — dbt's real strength is coordinating multiple contributors' changes to a shared model graph, which doesn't apply to a solo maintainer.

None of these are true today.

## 11. Metric definitions

Every metric below: precise definition, source model, and caveats. These are the canonical definitions — a future dashboard addition or ad hoc query should match these, not redefine them silently.

### Acquisition / activation
- **Conversations started** = `COUNT(*)` from `fact_conversations` in the period. Grain is the episode, not the raw session — see §5.1.
- **Unique anonymous visitors entering chat** = `COUNT(*) FILTER (WHERE user_id IS NULL)` from `fact_conversations`. *Caveat:* session-based, not device-based — clearing cookies or switching browsers counts as a new visitor.
- **Signup conversion** = `user_registered` count ÷ `signup_started` count, same period. *Caveat:* `signup_started` fires on every GET to the registration page including refreshes — treat as directional, not exact.
- **Anonymous → authenticated conversion** = `anonymous_user_authenticated` count (optionally filtered to `metadata.had_anonymous_conversation = true`) ÷ anonymous `fact_conversations` count. *Caveat:* manual login only this pass — a returning Google OAuth user is not captured (§13); the correlation window is unbounded (a login days after the anonymous session still counts).

### Engagement
- **Messages per conversation** = `AVG(message_count)` from `fact_conversations`.
- **Conversations reaching recommendation** = `COUNT(*) FILTER (WHERE reached_recommendation)` ÷ `COUNT(*)`, from `fact_conversations`.
- **Recommendations viewed** = not tracked separately — see §3.3.
- **Trips saved** = `destinations_saved` (from the mart) or `COUNT(*) FILTER (WHERE was_saved)` from `fact_recommendations` for the recommendation-attributed subset; `trip_created` events overall for the total including manually-logged trips (distinguishable via `metadata.source`, see §14).

### Recommendation quality
- **Recommendation acceptance rate** = `COUNT(*) FILTER (WHERE was_selected OR was_saved)` ÷ `COUNT(*)`, from `fact_recommendations`. *Caveat:* approximate session-based correlation (§5.5), not an ID-based join.
- **Save rate** = `COUNT(*) FILTER (WHERE was_saved)` ÷ `COUNT(*)`, from `fact_recommendations`.
- **Explicit positive/negative feedback rate** = `COUNT(*) FILTER (WHERE rating >= 8)` / `COUNT(*) FILTER (WHERE rating <= 4)` ÷ total, from `fact_feedback` (thresholds match `trips.tasks`'s own `POSITIVE_RATING_THRESHOLD`, kept consistent rather than inventing a second threshold).
- **Rejection rate** = `1 − acceptance rate`. Derived, not a raw event — see §3.3.
- **Destination-level performance** = `fact_recommendations` grouped by `destination_slug`: times recommended, times selected, times saved.

### AI / operational
- **AI request count / failure rate** = `COUNT(*)` / `COUNT(*) FILTER (WHERE NOT success)`, from `fact_ai_requests`, optionally grouped by `operation`.
- **Latency p50/p95/p99** = `percentile_cont(0.5|0.95|0.99) WITHIN GROUP (ORDER BY latency_ms)`, from `fact_ai_requests` — Postgres-native, no library. *Caveat:* latency/reliability only — no token/cost data this pass (§7).
- **Provider/model usage** = `GROUP BY operation, event_type` on `fact_ai_requests`.
- **Recommendation-generation latency** specifically = approximated as the sum of instrumented AI-call latencies within one turn (joinable via `conversation_key` + time proximity) — **not** true end-to-end request latency, which would need a dedicated request-level timing hook in `ai/views.py` (not built this pass — flagged in §13 as a specific, small, well-scoped future addition).

## 12. Performance considerations

- **No `CONN_MAX_AGE` pooling is configured anywhere in `config/settings/`** (confirmed before implementation) — every request opens/closes its own DB connection, including every warehouse view query. Not a new risk introduced by this pass, just worth restating: at real traffic, connection-per-request becomes the first thing to fix, before anything analytics-specific.
- **No separate analytics database or schema** — views live in the same Postgres instance/schema as the application tables (§ below on when to change this).
- **No read replica.** All warehouse queries hit the same connection pool as the transactional application. At current/near-future volume this is fine (the views are simple, the tables are small); the dashboard's own queries are bounded to a 30-day lookback window specifically to keep this cheap regardless.
- **The one place volume was a real, concrete risk during implementation** (not hypothetical): naively instrumenting `OpenMeteoClimateProvider.get_monthly_climate()` (called up to ~384 times per chat message, ~4,600 times per cache-warming run) would have multiplied write volume by orders of magnitude for zero new signal, since the overwhelming majority of those calls are cache hits. Caught before shipping (§7) — instrumented `_fetch()` instead, which only runs on an actual network call.
- **When to introduce a separate analytics schema/database:** when ad hoc dashboard/warehouse queries start measurably competing with request-serving queries for connections or I/O. Plausible only once there's real traffic — and the free-tier Postgres instance itself would need upgrading before that point regardless, making this a natural joint decision, not a premature one.
- **What changes at 10x volume:** the live views (all of them, except the mart) still compute on read — at 10x, `fact_conversations`/`fact_recommendations`'s window-function sessionization and correlated subqueries start being worth indexing more deliberately (currently only `event_type+created_at`, `user+created_at`, and `conversation_key` are indexed) or worth materializing selectively, the same way `DailyProductMetrics` already is. Not needed yet — premature indexing against data that doesn't exist would be guessing.
- **What changes at 100x volume:** this is roughly the point the dbt trigger conditions in §10 and the separate-database trigger above are both likely to fire together — a natural inflection to revisit both decisions jointly rather than piecemeal.

## 13. Known limitations

- **No token/cost-based AI metrics** — latency/reliability only (§7). Documented path: extend `AIProvider.stream_reply`'s contract, and/or instrument `ai.conversations._generate_subject`.
- **No anonymous→authenticated conversion tracking for the Google OAuth login-of-an-existing-account path** — manual login form only. Google OAuth signup (a *new* account) is covered by `user_registered`; a *returning* Google OAuth user hits the same `cycle_key()`-before-signal ordering that required a `LoginView` subclass for the manual path, via a different signal (`allauth`'s `pre_social_login`) that this pass deliberately does not wire up — shipping a path that would silently always record `had_anonymous_conversation=False` would be worse than not building it. Same "add it when it's real" precedent already used for `premium_started`/`affiliate_link_clicked`.
- **`fact_recommendations`'s correlation is approximate**, not a hard foreign key (§5.5).
- **No request-level end-to-end latency hook** in `ai/views.py` — "recommendation-generation latency" is approximated from summed instrumented AI-call latencies, not measured as one true wall-clock span from request-received to first-byte-streamed.
- **No alerting/paging infrastructure** — freshness and failure-rate problems are visible to someone who looks (the dashboard, Celery logs), not pushed to anyone. Consistent with the rest of this codebase (no Sentry/APM exists anywhere yet) — not a gap unique to analytics.

## 14. Files changed / added

- `analytics/models.py` — `Event.conversation_key`/`.locale`, 5 new `EVENT_TYPE_CHOICES`, `OPERATIONAL_EVENT_TYPES`, `DailyProductMetrics`.
- `analytics/services.py` — `record_event()` gained `conversation_key`/`locale` kwargs and the operational-event actor exemption.
- `analytics/instrumentation.py` (new) — `track_llm_call`/`track_provider_call`.
- `analytics/tasks.py` (new) — `refresh_daily_metrics`.
- `analytics/views.py`, `analytics/urls.py`, `analytics/templates/analytics/dashboard.html` (new) — the staff-only dashboard.
- `analytics/warehouse/` (new subpackage) — `sql/*.sql` (7 views + the mart's own parameterized query), `models.py` (unmanaged Django models), `tests/test_views.py`.
- `analytics/migrations/0002_*.py` through `0005_*.py`.
- `ai/orchestration.py` — `StreamingOrchestrationResult.recommendation_constraints`; `conversation_key` threaded through `_stream_ai_reply`/`_extract_climate_budget_signal`/`_handle_focus_destination`; `track_llm_call` wrapping `_extract_intent`/`_extract_climate_budget_signal`/`_stream_ai_reply`.
- `ai/views.py` — enriched `recommendation_generated` metadata, new `destination_selected` firing, `conversation_key`/`locale` threaded through every event fired from this view.
- `ai/templates/ai/chat.html` — "Save this trip" link carries `&source=chat_recommendation`.
- `integrations/climate/open_meteo.py` — `track_provider_call` wrapping `_fetch()`.
- `users/views.py` — `LoginView` subclass (pre-login session key capture), `signup_started` firing.
- `users/urls.py`, `users/signals.py` — wired the new `LoginView`; `track_anonymous_conversion` receiver.
- `trips/views.py`, `trips/templates/trips/trip_form.html` — `source` round-tripped through a hidden field to distinguish chat-recommendation saves from any other entry point.
- `core/views.py`, `core/tests/test_seo.py` — `/analytics/` added to `robots.txt` from day one.
- `config/settings/base.py` — new `CELERY_BEAT_SCHEDULE` entry.
- `config/urls.py` — `analytics.urls` wired in.

## 15. What should be built next

In rough priority order, none of it built this pass, all of it a natural continuation:

1. **Real AI cost metrics** — extend `AIProvider.stream_reply`'s contract to expose usage data (§7). The single highest-value next step once cost visibility becomes an operational need.
2. **A hard `recommendation_id`** if the approximate session-based correlation (§5.5) ever proves too imprecise in practice — thread it through the "Choose this trip"/"Save this trip" UI.
3. **Request-level end-to-end latency** in `ai/views.py`, for a true "time to first byte" metric rather than the current sum-of-AI-call-latencies approximation.
4. **The Google OAuth returning-user conversion gap** (§13) — once/if `allauth`'s `pre_social_login` signal is worth wiring up for this specific case.
5. **Provider instrumentation for real flight/hotel providers**, once any exist — `provider_request_completed` is already generic/reusable, no schema change needed.
6. **Revisit dbt and a separate analytics schema/database jointly** once either trigger condition in §10/§12 fires.
