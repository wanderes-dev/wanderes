# Decisions Pending — Human Input Required

Per `15_IMPLEMENTATION_GUIDE.md` §2 and §38, these decisions must be made or explicitly approved by you before implementation can continue. Claude Code should not choose these on its own. This file lists exactly what's blocking progress right now and enough context to decide efficiently. Once you decide, tell Claude Code and it will update this file and proceed.

---

## 1. AI Provider Selection (blocks Phase 2) — ✅ RESOLVED 2026-08-28

**Decision:** **OpenAI** (GPT models) is the AI provider for TravelAgent's conversational/reasoning layer.

**Product naming (not a technical decision, recorded here for continuity):** the AI assistant persona is named **"Lunna"** — this is user-facing copy/branding, independent of which provider powers it underneath.

**Explicit implementation priorities the user reinforced** (already required by the architecture docs, not new scope — flagged so they aren't skipped or under-built during Phase 2 implementation):

- Conversation context handled separately from persistent traveler memory — per `09_AI_ORCHESTRATION.md` §7.
- Context summarization — condensing conversation history instead of sending the full transcript every turn (supports §13 "avoid unnecessarily large conversation histories").
- Only relevant travel data is sent to the AI, never the whole database or full user history — per `09_AI_ORCHESTRATION.md` §4 and §11 ("The AI model should never be treated as having unrestricted access to the TravelAgent database").
- Caching where it makes sense — per `09_AI_ORCHESTRATION.md` §13 ("Reuse cached information where appropriate").
- The provider must sit behind the internal `AI Provider Abstraction` (`05_AI_DESIGN.md` §10, `09_AI_ORCHESTRATION.md` §11) so switching providers later does not require redesigning the recommendation system.

**Reference:** `15_IMPLEMENTATION_GUIDE.md` Phase 2; `05_AI_DESIGN.md` §10 (provider abstraction); `09_AI_ORCHESTRATION.md`; `14_MVP_IMPLEMENTATION_PLAN.md` §7 ("Spike A — AI Provider Evaluation").

### What needs to be decided

Which AI provider/model powers TravelAgent's conversational and reasoning layer. The architecture already requires this to sit behind an internal AI interface (`AI Provider Abstraction`), so switching later is possible but the *first* choice still needs to be made deliberately — it affects cost, latency, and how much structured-output/tool-use scaffolding is needed.

### What to evaluate (per the architecture docs)

- Response quality for conversational, explanation-heavy reasoning (not just factual Q&A).
- Streaming support (required — see `08_FRONTEND_ARCHITETURE.md` §4 and `09_AI_ORCHESTRATION.md` §8).
- Structured output / tool-use support (required — see `09_AI_ORCHESTRATION.md` §9, "Structured Output").
- Cost per request at expected usage volume (development budget ceiling is ~€100/month per `15_IMPLEMENTATION_GUIDE.md` §42).
- Data/privacy handling by the provider (relevant to `11_SECURITY_&_PRIVACY.md`).
- SDK quality / Python support.

### Candidates to consider (not a recommendation — your call)

- **Anthropic Claude** (Sonnet/Haiku tiers) — strong reasoning and instruction-following, native tool use, streaming.
- **OpenAI GPT** models — broad ecosystem, strong tool use, streaming.
- Smaller/cheaper models (e.g., a low-cost tier from either provider) for less critical tasks, if a two-tier strategy is wanted later — this is optional and not required for MVP.

### What Claude Code does once you decide

Implements the AI provider adapter behind the internal interface described in `05_AI_DESIGN.md` §10 — i.e., the rest of the app never talks to the provider's SDK directly.

---

## 2. Travel Data Provider Selection (blocks Phase 3) — ✅ RESOLVED 2026-08-28

**Decision:**

- **Destination data** (name, country, description, points of interest): a **curated static dataset**, provided/approved by the user, stored in the application (not a live external API for this piece). Explicitly documented here as a **deliberate MVP simplification** per `14_MVP_IMPLEMENTATION_PLAN.md` — revisit if/when destination breadth or freshness outgrows a static list.
- **Weather/climate data**: **Open-Meteo** (free, no API key required for the endpoints TravelAgent needs). Chosen specifically so it sits behind the internal Travel Data Interface (`10_EXTERNAL_INTEGRATIONS.md` §3) and can be swapped for another weather provider later without touching business logic — this replaceability was an explicit requirement from the user, not just the general architectural default.
- **Flights**: deferred, per the MVP plan (`14_MVP_IMPLEMENTATION_PLAN.md` §6 — not required for the first vertical slice).
- **Hotels**: deferred, same reasoning.

**Explicitly ruled out:** using the AI model's own parametric knowledge to generate destination facts instead of a real data source. Re-affirmed during this decision discussion that `05_AI_DESIGN.md` §7 already forbids the AI inventing travel data — the AI's role stays limited to reasoning/explaining over grounded data the application retrieves, both to avoid hallucinated facts about real places and to keep destination info consistent across AI provider changes (relevant since Phase 2 requires providers to stay swappable).

**Initial curated destination list: ✅ drafted and approved 2026-08-29.** Claude Code proposed an 18-destination draft (varied continents, trip types, and cost tiers); the user iterated on it (added a "worst season" field, changed cost-of-living from a 3-tier to a 1–5 scale) and approved the final version. Stored at [`travel/data/curated_destinations.json`](../travel/data/curated_destinations.json) — the source of truth to seed the `Destination` model once it's created in Phase 4. (Moved here from `documentation/data/` on 2026-08-30 - it's real application data the `load_destinations` command reads at runtime, not developer documentation, and living inside `documentation/` meant it was silently excluded from the Docker image by `.dockerignore` - see `DEVELOPMENT_LOG.md`'s Phase 18 deploy entry.)

**Reference:** `15_IMPLEMENTATION_GUIDE.md` Phase 3; `10_EXTERNAL_INTEGRATIONS.md`; `14_MVP_IMPLEMENTATION_PLAN.md` §6 (Milestone 3).

### What needs to be decided

At minimum, a **destination/travel-information data source** sufficient for the first vertical slice (Milestone 5: "I want somewhere warm in October, not too expensive" → a real, grounded recommendation). Flights and hotels can follow later — the MVP flow does not strictly require live flight/hotel booking data on day one, but needs *some* real destination/climate/cost data so recommendations aren't fabricated by the AI (explicitly forbidden — `05_AI_DESIGN.md` §7: "The AI should not invent travel data, availability, prices, reviews, or user history").

### Sub-decisions

1. **Destination & climate data** (needed first — powers the first vertical slice). Candidates to research: a geographic/climate API, or a curated static dataset you control initially (simpler, no external dependency, but must be disclosed as a deliberate MVP simplification if chosen).
2. **Flights** (can be deferred past the first vertical slice).
3. **Hotels** (can be deferred past the first vertical slice).
4. **Weather** (optional for MVP; relevant if seasonal/climate recommendations are central).

### What to evaluate (per `10_EXTERNAL_INTEGRATIONS.md` §2–3)

- Coverage and data quality.
- Reliability and rate limits.
- Cost (again, mind the ~€100/month ceiling during early development).
- Whether a free/sandbox tier exists for development.
- Licensing terms for redisplaying the data.

### What Claude Code does once you decide

Implements the provider adapter(s) behind the internal `Travel Data Interface` described in `10_EXTERNAL_INTEGRATIONS.md` §3, with response validation, normalization, and timeout handling (Milestone 3 deliverables in `14_MVP_IMPLEMENTATION_PLAN.md` §6).

---

## 3. Product Analytics Approach (blocks Phase 17) — ✅ RESOLVED 2026-08-30

**Decision:**

- **Approach: self-hosted, first-party.** A new `analytics` Django app with an `Event` model in our own Postgres - no third-party analytics vendor, no data ever leaves the app's own database. Consistent with every other choice so far (own DB, own auth, no vendor lock-in) and avoids the privacy tradeoff of sending user behavior data to an external provider.
- **Events instrumented now**: `user_registered`, `profile_completed`, `travel_question_submitted`, `recommendation_generated`, `trip_created`, `feedback_submitted`. `travel_question_submitted` fires for *any* chat interaction, regardless of what it turns out to be (recommendation, feedback, future intent, or off-topic).
- **`premium_started` and `affiliate_link_clicked` deliberately deferred** - the guide's candidate list includes them, but monetization/premium and an affiliate provider don't exist in the app yet (both still-undecided human decisions). Add them when those features are actually built.
- **`recommendation_viewed` deliberately not created** - there is no separate results page; a recommendation already appears inline within the streamed chat reply, so a distinct "viewed" event would be redundant.
- **Anonymous visitors tracked by anonymized IP, not a session identifier** - last IPv4 octet zeroed / IPv6 masked to its /48 prefix before ever being stored (same technique as Google Analytics'/Matomo's IP anonymization). Authenticated events store the user, never an IP.
- **"Active user" definition** (the guide requires documenting this before using it for business decisions): an authenticated user who submitted at least one chat message (`travel_question_submitted`) within the window - 1 day for DAU, 7 for WAU, 30 for MAU. Anonymous chat use is tracked but never counts toward these.
- **Privacy**: only small structured metadata is ever stored (e.g. a destination slug, a rating) - never free-text message or comment content. A simple, non-blocking transparency note was added to `templates/base.html`'s footer, since this is genuinely new data collection starting now - not a full cookie-consent banner, which the guide places in a later, pre-launch GDPR review phase (near Phase 30) that hasn't started yet.

**Reference:** `15_IMPLEMENTATION_GUIDE.md` Phase 17; `11_SECURITY_&_PRIVACY.md` §11-12 (privacy/GDPR principles - purpose limitation, data minimization, transparency).

### What Claude Code did once decided

Implemented the `analytics` app (`Event` model, `services.record_event()`, `metrics.py` for DAU/WAU/MAU/retention/per-active-user rates, Django admin registration), wired `record_event()` calls into registration, profile completion, the chat view, conversational feedback/future-intent, and the standalone trip/feedback forms. See `DEVELOPMENT_LOG.md` for the full implementation record.

---

## How to unblock

Reply with your decision(s) — even a partial one (e.g., "let's start with just a destination dataset and Anthropic Claude, defer flights/hotels") is enough to resume work. Claude Code will then:

1. Update this file (mark the decision resolved, with the date and what was chosen).
2. Update `PROJECT_STATE.md`.
3. Add a `DEVELOPMENT_LOG.md` entry.
4. Implement the corresponding adapter(s).
