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

**Next actionable step:** the user needs to supply (or approve a Claude-Code-proposed draft of) the initial curated destination list before the destination data adapter can be implemented for real.

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

## How to unblock

Reply with your decision(s) — even a partial one (e.g., "let's start with just a destination dataset and Anthropic Claude, defer flights/hotels") is enough to resume work. Claude Code will then:

1. Update this file (mark the decision resolved, with the date and what was chosen).
2. Update `PROJECT_STATE.md`.
3. Add a `DEVELOPMENT_LOG.md` entry.
4. Implement the corresponding adapter(s).
