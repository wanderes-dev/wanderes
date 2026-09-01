# Decisions Pending — Human Input Required

Per `15_IMPLEMENTATION_GUIDE.md` §2 and §38, these decisions must be made or explicitly approved by you before implementation can continue. Claude Code should not choose these on its own. This file lists exactly what's blocking progress right now and enough context to decide efficiently. Once you decide, tell Claude Code and it will update this file and proceed.

---

## 1. AI Provider Selection (blocks Phase 2) — ✅ RESOLVED 2026-08-28

**Decision:** **OpenAI** (GPT models) is the AI provider for TravelAgent's conversational/reasoning layer.

**Product naming (not a technical decision, recorded here for continuity):** the AI assistant persona is named **"Wander"** — this is user-facing copy/branding, independent of which provider powers it underneath. (Originally named "Lunna"; renamed to "Wander" on 2026-08-30 per direct user request.)

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

## 4. Flight & Hotel Affiliate Provider Selection (blocks Phase 24) — ✅ FLIGHTS RESOLVED 2026-09-01 (Duffel); hotels still open

**Decision (flights): Duffel is the MVP flight provider.** Chosen specifically because it's the only researched option accessible right now without a traffic/MAU minimum TravelAgent doesn't have pre-launch - see the comparison below. Explicitly **not** a permanent commitment: the `FlightProvider` interface (`10_EXTERNAL_INTEGRATIONS.md` §13) is designed so Skyscanner, KAYAK, Amadeus Enterprise, or direct airline/NDC connections can replace or supplement Duffel later without touching the recommendation engine, traveler profile, trips, AI orchestration, or chat UI - only a new adapter behind the same interface.

**Still open, and needs your input before implementation proceeds (see "Human Review" below)**: the exact booking-flow shape (Duffel's core Flights API + Duffel's Payments API vs. the lower-code "Duffel Links" hosted checkout - these appear to have *different* markup mechanics per Duffel's own docs, not fully reconcilable from public pages alone) and the markup/commission economics. Hotels (Booking.com Affiliate Partner Program was the front-runner from the original research) are **not part of this decision** - this request was flights-only; hotels remain pending.

**Requested out of sequence 2026-09-01** — Phase 19-22 (Premium Strategy/Entitlements, Payment Provider/Integration) haven't started; this jumps ahead to Phase 23/24 material at the user's explicit direction. Noted here for an honest record, not a reason to refuse: this is research and documentation only for now (implementation is Phase 24, "Claude Code + Human Review" per `15_IMPLEMENTATION_GUIDE.md`), and Phase 23 is explicitly "Human Decision + Research."

**The headline finding, upfront**: every genuine real-time flight/hotel *search* API researched (not just a banner link) gates access behind a traffic/volume threshold TravelAgent doesn't have yet as a pre-launch MVP - commonly 50,000-100,000+ monthly users, sometimes phrased as "established business," sometimes as an explicit MAU minimum. This isn't a TravelAgent-specific problem; it's the standard shape of this industry's provider ecosystem. Two real options exist anyway (see recommendation below), but both come with trade-offs the guide's "no assumptions" instruction means should go to you, not get decided quietly.

### What was researched

**Flights:**

| Provider | Access model | Startup accessibility now | Notes |
|---|---|---|---|
| **Skyscanner** | Affiliate Programme (deep-links, via impact.com) vs. Travel API (real search) | Affiliate: needs 5,000+ monthly visitors. Travel API: needs an "established business" with >100k monthly traffic, and explicitly excludes "start-ups without a robust business plan and pre-developed product." | Neither tier is realistically open to TravelAgent today. [Partner support: acceptance criteria](https://skyscannerpartnersupport.zendesk.com/hc/en-us/articles/10881149122717-What-is-the-acceptance-criteria-for-the-Travel-API), [affiliate programme criteria](https://skyscannerpartnersupport.zendesk.com/hc/en-us/articles/10877740886045-Getting-Started-What-is-the-acceptance-criteria-for-the-programme) |
| **KAYAK** | Affiliate network + API, via affiliates.kayak.com | Affiliate program is effectively aimed at sites with ~1M+ monthly visitors per third-party sources; API access requires a manual business application, an assigned account manager, and has no public docs/OpenAPI spec/sandbox until approved - "small developers and hobbyists are typically declined." | Not accessible now despite the application form offering a "Sandbox APIs" checkbox - that's a step *after* business approval, not open self-serve. [API assessment](https://supergood.ai/api-report-card/kayak) |
| **Kiwi.com (Tequila API)** | Self-serve API | Self-serve registration closed May 2024; now invitation-only. The Travelpayouts-routed affiliate path needs 50,000+ MAU. | Not accessible now. |
| **Amadeus for Developers (Self-Service)** | Free/low-cost self-serve tier, historically the standard startup on-ramp | **Fully decommissioned 2026-07-17** - new registrations were already paused before that. This is very recent and changes the landscape materially versus older guidance. Amadeus Enterprise still exists but is a full commercial GDS relationship, not a startup path. | Confirmed via independent trade press ([PhocusWire](https://www.phocuswire.com/amadeus-shut-down-self-service-apis-portal-developers)), not just a vendor blog. |
| **Aviasales, via Travelpayouts** | Real-time Flight Search API vs. Data API (cached trends) | Real-time search API needs 50,000+ MAU. The Data API has no MAU minimum but only returns cached historical price-trend/popular-destination data, not live per-query results - useful for "typical price" content, not for scoring real flight options. | Real-time search not accessible now. |
| **Duffel** | Self-serve, sign-up in under a minute, free Starter plan (~50 bookings/month, no fixed fee) | **Accessible right now, no traffic minimum.** Handles IATA accreditation on the partner's behalf. | **Different architecture, not just a different vendor** - see below. |
| **Travelpayouts (network)** | Free instant sign-up, aggregates 90+ travel brands' affiliate links (incl. Aviasales, Booking.com) | **Accessible right now, no traffic minimum.** | Gives redirect links, not live structured search data to filter/score against - closer to a "search flights to X" call-to-action than a real recommendation input. |

**Hotels:**

| Provider | Access model | Startup accessibility now | Notes |
|---|---|---|---|
| **Booking.com Affiliate Partner Program** | Application-reviewed, free once approved | Open to "a wide range of applicants, from large companies... to travel bloggers" - no hard traffic minimum found, though approval isn't instant (one source noted new Connectivity applications paused pending a Terms update, separate from the basic Affiliate tier). Approved partners get a real XML feed (hotel info, photos, **real-time pricing and availability**), commission 25-40% of Booking.com's own cut. | **The most promising hotel option for TravelAgent's current stage.** |
| **Duffel Stays** | Same self-serve platform as Duffel Flights | Not separately verified in depth, but reasonable to assume similar accessibility given the shared platform - would need direct confirmation before relying on it. | Same architectural note as Duffel Flights applies. |
| **Skyscanner / KAYAK Hotels APIs** | Same programs as their flight APIs | Same high-traffic gating as flights. | Not accessible now. |

### The real fork: two fundamentally different architectures, not just two vendors

1. **Pure affiliate redirect** (Skyscanner, KAYAK, Booking.com Affiliate, Travelpayouts) - TravelAgent shows options, the user clicks through and completes the purchase on the *provider's own site*, TravelAgent earns a referral commission. This matches the brief's stated flow exactly (`Recommendation → Affiliate Link → External Website → Booking → Commission`) and keeps TravelAgent furthest from ever needing to be a merchant of record, handle payments, or manage bookings/cancellations - the explicit "we are not building Booking.com" boundary stays clean.
2. **Book-through-API / hosted checkout** (Duffel) - TravelAgent integrates Duffel's API and either books directly or redirects to "Duffel Links," a *Duffel-hosted*, TravelAgent-branded checkout page. The customer still doesn't check out on TravelAgent's own infrastructure, but TravelAgent is now functionally reselling Duffel's inventory and earning a revenue *share*, not a referral *commission* - a meaningfully different commercial relationship (closer to a light travel-agency role than a pure affiliate), even though it's the only flights option that's actually usable today without a traffic minimum.

This distinction - not just "which brand" - is the crux of the decision, and it's exactly the kind of business-model call `15_IMPLEMENTATION_GUIDE.md` reserves for you, not Claude Code.

### Claude Code's recommendation (not a decision - your call, per the brief)

If real flight/hotel search is wanted **now**, before TravelAgent has meaningful traffic: **Duffel for flights + Booking.com Affiliate Partner Program for hotels** is the only combination that's actually reachable at this stage - everything else requires traffic TravelAgent doesn't have yet. This means accepting the Duffel Links revenue-share model for flights (a real, if minor, departure from "pure affiliate only") while keeping hotels as a clean traditional affiliate redirect. **Travelpayouts is worth adding regardless of the above** as a zero-cost, zero-barrier fallback/supplement (covers both categories with simple links), even though it can't power real search/filtering.

If staying strictly "pure affiliate, no hosted-checkout revenue-share" is a hard requirement: the honest answer is to defer flights entirely until TravelAgent has enough traffic to qualify for Skyscanner/KAYAK/Kiwi (a real, unknown amount of time), and launch with hotels only via Booking.com's Affiliate Partner Program (or Travelpayouts links as a stopgap) in the meantime.

### What needs to be decided

- Which flight provider(s) to pursue, and specifically: **is the Duffel Links revenue-share model acceptable**, or should flights wait for a pure-affiliate provider to become accessible?
- Which hotel provider(s) to pursue (Booking.com Affiliate Partner Program is the clear front-runner from this research).
- Whether to add Travelpayouts as a lightweight supplementary layer regardless of the above.
- Commission/revenue-share expectations and how that interacts with the already-established "recommendations must never be influenced by commission" principle (`10_EXTERNAL_INTEGRATIONS.md` §9, reaffirmed in the brief for this task).
- Geographic coverage requirements (not deeply researched here - would need clarifying what markets TravelAgent targets first).
- Timing: pursue this now (accepting Duffel's different model for flights) or defer until real traffic exists (delaying flight search, hotels-only via Booking.com in the meantime)?

### Duffel commercial model - verified, with explicit "confirm directly" flags

Per the instruction not to hard-code assumed commercial terms, here's what's publicly documented on [duffel.com/pricing](https://duffel.com/pricing) and [duffel.com/docs/guides/margin-and-markups](https://duffel.com/docs/guides/margin-and-markups), and what still needs direct confirmation with Duffel:

- **Pay As You Go plan** (the one relevant to an MVP): zero up-front cost, no subscription.
- **Fees**: $3.00 per confirmed flight order (monthly billing), 1% of order value for "Managed Content," $2.00 per paid ancillary (e.g. extra baggage), $0.005 per search once search-to-book ratio exceeds 1,500:1, 2% on currency conversions.
- **Markup**: possible, but the mechanics genuinely differ by integration path per Duffel's own docs, and public pages weren't fully consistent on this - **requires confirmation with Duffel directly**:
  - Full Flights API + Duffel Payments API: Duffel passes through its net cost; TravelAgent would build its own markup logic and use Duffel as merchant of record to actually charge the customer. More integration work, full control over pricing/margin.
  - "Duffel Links" (low-code hosted checkout, "no development resources needed" per Duffel's own marketing): appears to support markup directly via Duffel's own dashboard - much less integration work, less control.
- **Stays (hotels)**: a separate profit-share model on completed bookings; the percentage is not publicly disclosed - **requires confirmation with Duffel directly**. Not part of this flights decision regardless.
- **IATA accreditation**: handled by Duffel (shared across 5 global IATAs it holds) - included in the Managed Content fee, not a separate cost or a barrier for TravelAgent.

### Human Review — before any implementation code is written (per the brief's own Step 5)

These are the specific items that need your explicit sign-off before Claude Code proceeds past design/documentation into actual `DuffelFlightProvider` code:

1. **Booking-flow shape**: Duffel Links (fast to integrate, markup via Duffel's dashboard, less TravelAgent control) vs. the full Flights + Payments API (more integration work, full markup control, TravelAgent closer to merchant-of-record territory). This is as much a business-model choice as a technical one.
2. **Markup vs. flat revenue-share economics** - and how either interacts with the standing "recommendations must never be influenced by commission" rule (`10_EXTERNAL_INTEGRATIONS.md` §9 and §13.3) - scoring must stay blind to which option earns more.
3. **Whether the MVP exposes actual booking/checkout at all in this first pass**, or stops at "search, recommend, explain, hand off to Duffel's flow" without wiring up markup/payments logic yet - a materially smaller first slice.
4. **Fee absorption**: whether the $3/order + ancillary fees are absorbed by TravelAgent, passed to the traveler via markup, or left unaddressed until real bookings happen.
5. Confirmation that pursuing this now (pre-traffic) is worth the Duffel-specific commercial relationship, versus waiting - i.e. re-affirming the timing decision above now that the concrete fee schedule is known.

### What Claude Code does once you decide

Design and implement the `FlightProvider`/`HotelProvider` internal interfaces described in `10_EXTERNAL_INTEGRATIONS.md` §3 (not yet done - this entry is research only), then the adapter(s) for whichever provider(s) are approved, with response validation, normalization into `FlightOption`/`HotelOption` internal representations, timeout/error handling, affiliate/deep-link generation, and tests - per Phase 24's Claude Code responsibilities in `15_IMPLEMENTATION_GUIDE.md`. Account creation with any provider, and any commercial/API agreement, remains something only you can do - Claude Code cannot create provider accounts or assume affiliate eligibility on your behalf.

**Reference:** `15_IMPLEMENTATION_GUIDE.md` Phase 23-24; `10_EXTERNAL_INTEGRATIONS.md` §9 (Booking & Affiliate Providers) and new §13 (this research, full detail).

---

## How to unblock

Reply with your decision(s) — even a partial one (e.g., "let's start with just a destination dataset and Anthropic Claude, defer flights/hotels") is enough to resume work. Claude Code will then:

1. Update this file (mark the decision resolved, with the date and what was chosen).
2. Update `PROJECT_STATE.md`.
3. Add a `DEVELOPMENT_LOG.md` entry.
4. Implement the corresponding adapter(s).
