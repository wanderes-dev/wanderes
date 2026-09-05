# Decisions Pending — Human Input Required

Per `15_IMPLEMENTATION_GUIDE.md` §2 and §38, these decisions must be made or explicitly approved by you before implementation can continue. Claude Code should not choose these on its own. This file lists exactly what's blocking progress right now and enough context to decide efficiently. Once you decide, tell Claude Code and it will update this file and proceed.

---

## 1. AI Provider Selection (blocks Phase 2) — ✅ RESOLVED 2026-08-28

**Decision:** **OpenAI** (GPT models) is the AI provider for Wanderes's conversational/reasoning layer.

**Product naming (not a technical decision, recorded here for continuity):** the AI assistant persona is named **"Wander"** — this is user-facing copy/branding, independent of which provider powers it underneath. (Originally named "Lunna"; renamed to "Wander" on 2026-08-30 per direct user request.)

**Explicit implementation priorities the user reinforced** (already required by the architecture docs, not new scope — flagged so they aren't skipped or under-built during Phase 2 implementation):

- Conversation context handled separately from persistent traveler memory — per `09_AI_ORCHESTRATION.md` §7.
- Context summarization — condensing conversation history instead of sending the full transcript every turn (supports §13 "avoid unnecessarily large conversation histories").
- Only relevant travel data is sent to the AI, never the whole database or full user history — per `09_AI_ORCHESTRATION.md` §4 and §11 ("The AI model should never be treated as having unrestricted access to the Wanderes database").
- Caching where it makes sense — per `09_AI_ORCHESTRATION.md` §13 ("Reuse cached information where appropriate").
- The provider must sit behind the internal `AI Provider Abstraction` (`05_AI_DESIGN.md` §10, `09_AI_ORCHESTRATION.md` §11) so switching providers later does not require redesigning the recommendation system.

**Reference:** `15_IMPLEMENTATION_GUIDE.md` Phase 2; `05_AI_DESIGN.md` §10 (provider abstraction); `09_AI_ORCHESTRATION.md`; `14_MVP_IMPLEMENTATION_PLAN.md` §7 ("Spike A — AI Provider Evaluation").

### What needs to be decided

Which AI provider/model powers Wanderes's conversational and reasoning layer. The architecture already requires this to sit behind an internal AI interface (`AI Provider Abstraction`), so switching later is possible but the *first* choice still needs to be made deliberately — it affects cost, latency, and how much structured-output/tool-use scaffolding is needed.

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
- **Weather/climate data**: **Open-Meteo** (free, no API key required for the endpoints Wanderes needs). Chosen specifically so it sits behind the internal Travel Data Interface (`10_EXTERNAL_INTEGRATIONS.md` §3) and can be swapped for another weather provider later without touching business logic — this replaceability was an explicit requirement from the user, not just the general architectural default.
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

## 4. Flight & Hotel Affiliate Provider Selection (blocks Phase 24) — 🔵 RESEARCH DONE, decision pending (flights: KAYAK, hotels: Booking.com - both named as intended providers, neither yet accessible)

**Update 2026-09-02**: the user has indicated **KAYAK** specifically as the intended flight provider - not a full "implement it now" decision (the access barrier documented below is unchanged: KAYAK's affiliate program needs ~1M+ monthly visitors and its API requires manual business approval with no public docs until then), but "prepare the internal interface now, so wiring in the real adapter is all that's left once access is granted." Distinct from the earlier Duffel decision (made, then explicitly reverted the same day) - that was a live "use this provider now" commitment; this is deliberately just the swappable-interface scaffolding, with no working KAYAK adapter behind it yet. See `10_EXTERNAL_INTEGRATIONS.md` §13.6 for what was actually built.

**Update 2026-09-04**: the user has similarly indicated **Booking.com** (its Affiliate Partner Program - already this research's own front-runner for hotels, see the table below) as the intended hotel provider, same "prepare the internal interface now" framing as the KAYAK request above - not a live "apply for and use this now" commitment. `HotelProvider`/`HotelOption` are now scaffolded exactly like the flight interface, with `integrations/hotels/booking_com.py` a deliberate skeleton (no real XML feed access yet). See `10_EXTERNAL_INTEGRATIONS.md` §13.7 for what was actually built. The underlying business questions below (commission expectations, geographic coverage, whether Booking.com is the final choice vs. also evaluating Duffel Stays) remain open - this is scaffolding, not a closed decision.

**Requested out of sequence 2026-09-01** — Phase 19-22 (Premium Strategy/Entitlements, Payment Provider/Integration) haven't started; this jumps ahead to Phase 23/24 material at the user's explicit direction. Noted here for an honest record, not a reason to refuse: this is research and documentation only, nothing was implemented, and `15_IMPLEMENTATION_GUIDE.md` itself lists Phase 23's owner as "Human Decision + Research" - exactly what this is.

**The headline finding, upfront**: every genuine real-time flight/hotel *search* API researched (not just a banner link) gates access behind a traffic/volume threshold Wanderes doesn't have yet as a pre-launch MVP - commonly 50,000-100,000+ monthly users, sometimes phrased as "established business," sometimes as an explicit MAU minimum. This isn't a Wanderes-specific problem; it's the standard shape of this industry's provider ecosystem. Two real options exist anyway (see recommendation below), but both come with trade-offs the guide's "no assumptions" instruction means should go to you, not get decided quietly.

### What was researched

**Flights:**

| Provider | Access model | Startup accessibility now | Notes |
|---|---|---|---|
| **Skyscanner** | Affiliate Programme (deep-links, via impact.com) vs. Travel API (real search) | Affiliate: needs 5,000+ monthly visitors. Travel API: needs an "established business" with >100k monthly traffic, and explicitly excludes "start-ups without a robust business plan and pre-developed product." | Neither tier is realistically open to Wanderes today. [Partner support: acceptance criteria](https://skyscannerpartnersupport.zendesk.com/hc/en-us/articles/10881149122717-What-is-the-acceptance-criteria-for-the-Travel-API), [affiliate programme criteria](https://skyscannerpartnersupport.zendesk.com/hc/en-us/articles/10877740886045-Getting-Started-What-is-the-acceptance-criteria-for-the-programme) |
| **KAYAK** | Affiliate network + API, via affiliates.kayak.com | Affiliate program is effectively aimed at sites with ~1M+ monthly visitors per third-party sources; API access requires a manual business application, an assigned account manager, and has no public docs/OpenAPI spec/sandbox until approved - "small developers and hobbyists are typically declined." | Not accessible now despite the application form offering a "Sandbox APIs" checkbox - that's a step *after* business approval, not open self-serve. [API assessment](https://supergood.ai/api-report-card/kayak) |
| **Kiwi.com (Tequila API)** | Self-serve API | Self-serve registration closed May 2024; now invitation-only. The Travelpayouts-routed affiliate path needs 50,000+ MAU. | Not accessible now. |
| **Amadeus for Developers (Self-Service)** | Free/low-cost self-serve tier, historically the standard startup on-ramp | **Fully decommissioned 2026-07-17** - new registrations were already paused before that. This is very recent and changes the landscape materially versus older guidance. Amadeus Enterprise still exists but is a full commercial GDS relationship, not a startup path. | Confirmed via independent trade press ([PhocusWire](https://www.phocuswire.com/amadeus-shut-down-self-service-apis-portal-developers)), not just a vendor blog. |
| **Aviasales, via Travelpayouts** | Real-time Flight Search API vs. Data API (cached trends) | Real-time search API needs 50,000+ MAU. The Data API has no MAU minimum but only returns cached historical price-trend/popular-destination data, not live per-query results - useful for "typical price" content, not for scoring real flight options. | Real-time search not accessible now. |
| **Duffel** | Self-serve, sign-up in under a minute, free Starter plan (~50 bookings/month, no fixed fee) | **Accessible right now, no traffic minimum.** Handles IATA accreditation on the partner's behalf. | **Different architecture, not just a different vendor** - see below. |
| **Travelpayouts (network)** | Free instant sign-up, aggregates 90+ travel brands' affiliate links (incl. Aviasales, Booking.com) | **Accessible right now, no traffic minimum.** | Gives redirect links, not live structured search data to filter/score against - closer to a "search flights to X" call-to-action than a real recommendation input. |

**Hotels:**

| Provider | Access model | Startup accessibility now | Notes |
|---|---|---|---|
| **Booking.com Affiliate Partner Program** | Application-reviewed, free once approved | Open to "a wide range of applicants, from large companies... to travel bloggers" - no hard traffic minimum found, though approval isn't instant (one source noted new Connectivity applications paused pending a Terms update, separate from the basic Affiliate tier). Approved partners get a real XML feed (hotel info, photos, **real-time pricing and availability**), commission 25-40% of Booking.com's own cut. | **The most promising hotel option for Wanderes's current stage.** |
| **Duffel Stays** | Same self-serve platform as Duffel Flights | Not separately verified in depth, but reasonable to assume similar accessibility given the shared platform - would need direct confirmation before relying on it. | Same architectural note as Duffel Flights applies. |
| **Skyscanner / KAYAK Hotels APIs** | Same programs as their flight APIs | Same high-traffic gating as flights. | Not accessible now. |

### The real fork: two fundamentally different architectures, not just two vendors

1. **Pure affiliate redirect** (Skyscanner, KAYAK, Booking.com Affiliate, Travelpayouts) - Wanderes shows options, the user clicks through and completes the purchase on the *provider's own site*, Wanderes earns a referral commission. This matches the brief's stated flow exactly (`Recommendation → Affiliate Link → External Website → Booking → Commission`) and keeps Wanderes furthest from ever needing to be a merchant of record, handle payments, or manage bookings/cancellations - the explicit "we are not building Booking.com" boundary stays clean.
2. **Book-through-API / hosted checkout** (Duffel) - Wanderes integrates Duffel's API and either books directly or redirects to "Duffel Links," a *Duffel-hosted*, Wanderes-branded checkout page. The customer still doesn't check out on Wanderes's own infrastructure, but Wanderes is now functionally reselling Duffel's inventory and earning a revenue *share*, not a referral *commission* - a meaningfully different commercial relationship (closer to a light travel-agency role than a pure affiliate), even though it's the only flights option that's actually usable today without a traffic minimum.

This distinction - not just "which brand" - is the crux of the decision, and it's exactly the kind of business-model call `15_IMPLEMENTATION_GUIDE.md` reserves for you, not Claude Code.

### Claude Code's recommendation (not a decision - your call, per the brief)

If real flight/hotel search is wanted **now**, before Wanderes has meaningful traffic: **Duffel for flights + Booking.com Affiliate Partner Program for hotels** is the only combination that's actually reachable at this stage - everything else requires traffic Wanderes doesn't have yet. This means accepting the Duffel Links revenue-share model for flights (a real, if minor, departure from "pure affiliate only") while keeping hotels as a clean traditional affiliate redirect. **Travelpayouts is worth adding regardless of the above** as a zero-cost, zero-barrier fallback/supplement (covers both categories with simple links), even though it can't power real search/filtering.

If staying strictly "pure affiliate, no hosted-checkout revenue-share" is a hard requirement: the honest answer is to defer flights entirely until Wanderes has enough traffic to qualify for Skyscanner/KAYAK/Kiwi (a real, unknown amount of time), and launch with hotels only via Booking.com's Affiliate Partner Program (or Travelpayouts links as a stopgap) in the meantime.

### What needs to be decided

- Which flight provider(s) to pursue, and specifically: **is the Duffel Links revenue-share model acceptable**, or should flights wait for a pure-affiliate provider to become accessible?
- Which hotel provider(s) to pursue (Booking.com Affiliate Partner Program is the clear front-runner from this research).
- Whether to add Travelpayouts as a lightweight supplementary layer regardless of the above.
- Commission/revenue-share expectations and how that interacts with the already-established "recommendations must never be influenced by commission" principle (`10_EXTERNAL_INTEGRATIONS.md` §9, reaffirmed in the brief for this task).
- Geographic coverage requirements (not deeply researched here - would need clarifying what markets Wanderes targets first).
- Timing: pursue this now (accepting Duffel's different model for flights) or defer until real traffic exists (delaying flight search, hotels-only via Booking.com in the meantime)?

### What Claude Code does once you decide

The `FlightProvider`/`HotelProvider` internal interfaces described in `10_EXTERNAL_INTEGRATIONS.md` §3 are now scaffolded (§13.6/§13.7 - `integrations/flights/`, `integrations/hotels/`), each with a deliberate skeleton adapter (`KayakFlightProvider`, `BookingComHotelProvider`) that raises `NotImplementedError` rather than guessing at undocumented request/response shapes. Once real API access/documentation exists for either provider, filling in that adapter's methods (response validation, normalization into `FlightOption`/`HotelOption`, timeout/error handling, affiliate/deep-link generation, and tests) is the only code change needed - per Phase 24's Claude Code responsibilities in `15_IMPLEMENTATION_GUIDE.md`. Account creation with any provider, and any commercial/API agreement, remains something only you can do - Claude Code cannot create provider accounts or assume affiliate eligibility on your behalf.

**Reference:** `15_IMPLEMENTATION_GUIDE.md` Phase 23-24; `10_EXTERNAL_INTEGRATIONS.md` §9 (Booking & Affiliate Providers) and new §13 (this research, full detail).

---

## 5. Google OAuth Login — 🟢 CODE READY, real Google Cloud credentials needed (not a Claude Code decision - account creation only)

**2026-09-03, direct user request: "prepare para podermos fazer login atraves do google."** Unlike the other entries above, there's no product/architecture decision left to make here - the user already decided to add Google login (also referenced back on 2026-08-29's account docs). This entry exists only to record the one remaining step that genuinely can't be done from source code: creating real OAuth credentials, which requires the user's own Google account.

**What's built and working** (`django-allauth`, additive to the existing email/password login - never a replacement): the Google provider is fully wired (`INSTALLED_APPS`, `AUTHENTICATION_BACKENDS`, `SOCIALACCOUNT_PROVIDERS`, `/accounts/google/login/` routing), a data migration keeps `django.contrib.sites`'s `Site` row in sync with `SITE_DOMAIN`, and a "Continue with Google" button was added to both the login and register pages. Verified live in a browser with a fake client ID: clicking the button correctly reaches Google's own OAuth endpoint and gets Google's own "invalid_client" rejection - proof the integration itself is wired correctly, only real credentials are missing.

**Deliberately safe in the meantime**: with `GOOGLE_OAUTH_CLIENT_ID`/`GOOGLE_OAUTH_CLIENT_SECRET` unset (both default to `""`), the button doesn't render at all (`core.context_processors.site_meta`'s `google_oauth_configured` flag) - real visitors never see a broken "Continue with Google" button that would otherwise redirect to Google with an empty client ID.

### What you need to do (Google Cloud Console, your own account)

1. Go to [console.cloud.google.com](https://console.cloud.google.com/) → create or select a project → **APIs & Services → OAuth consent screen** → configure it (app name "Wanderes", support email, etc.) - Google will likely require this before letting you create credentials.
2. **APIs & Services → Credentials → Create Credentials → OAuth client ID → Web application.**
3. Add these **Authorized redirect URIs** exactly (trailing slash matters):
   - `https://www.wanderes.com/accounts/google/login/callback/` (production)
   - `http://localhost:8000/accounts/google/login/callback/` (local dev, optional)
4. Copy the generated **Client ID** and **Client Secret**.
5. On Render: `wanderes-web` service → Environment → add `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET` with those values (these were added to `render.yaml` as `sync: false`, same pattern as `OPENAI_API_KEY` - but since the Blueprint was already created before this change, Render won't auto-prompt for them the way it did during initial setup; they need to be entered manually in the dashboard once).
6. Redeploy (or Render may pick up the env var change automatically depending on plan/settings) - the button appears on `/users/login/` and `/users/register/` as soon as both values are set, no further code changes needed.

### What Claude Code cannot do

Create the Google Cloud project, agree to Google's terms, or generate real credentials - this is tied to the user's own Google account, the same boundary already documented for KAYAK's business-approval requirement above.

**Reference:** `users/apps.py`, `users/signals.py` (analytics parity with the manual registration path), `users/tests/test_google_oauth.py`, `config/settings/base.py`'s `ACCOUNT_*`/`SOCIALACCOUNT_*` settings.

---

## 6. Password Reset via Emailed Token — 🟢 CODE READY, real SMTP credentials needed (provider choice is yours, not Claude Code's)

**2026-09-04, direct user request: "configure a recuperação de senha atraves de token, enviado por email."** Built entirely on Django's own `PasswordResetView`/`PasswordResetConfirmView`/token generator - the same "Django's own built-in auth, no custom reimplementation" convention already used for login/logout/registration (`07_API_DESIGN.md` §3). The one thing left is real SMTP credentials, and deliberately not one specific vendor - same boundary as every other external provider in this project.

**What's built and working**: `/users/password-reset/` (request form) → `/users/password-reset/done/` (a deliberately vague "check your email" page - never confirms whether an account exists, Django's own security convention) → the emailed link → `/users/reset/<uidb64>/<token>/` (set a new password, or an honest "this link no longer works" if it's already used or expired) → `/users/reset/done/`. The email itself uses `django.contrib.sites`'s `Site` row for its domain (kept in sync with `SITE_DOMAIN`, the same one canonical hostname everything else in this app uses), so the link is always `https://www.wanderes.com/...` regardless of which hostname the reset was actually requested from - verified live, not assumed, given the exact class of domain-mismatch bug that caused an outage earlier the same day.

**Deliberately safe in the meantime**: with `EMAIL_HOST` unset (default), Django uses its own console backend - a password-reset request always "succeeds" from the visitor's point of view (no 500, matching the same never-reveal-account-existence convention above) but genuinely delivers nothing anyone can see. The "Forgot your password?" link itself stays hidden until `EMAIL_HOST` is actually set (`core.context_processors.site_meta`'s `email_configured` flag, the same pattern as `google_oauth_configured`) - showing a recovery link that silently can't deliver anything would be its own kind of broken-in-production surprise, exactly what this project has been careful to avoid.

### What you need to do (pick any SMTP provider - your call)

1. Choose an SMTP provider - SendGrid, Mailgun, AWS SES (via its SMTP interface), Postmark, or even a plain Gmail account with an app password all work, since nothing here is vendor-specific. Get its SMTP host/port/username/password.
2. On Render: `wanderes-web` service → Environment → set `EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` (these are `sync: false` in `render.yaml`, so they need entering manually, same reason as the Google OAuth credentials). `EMAIL_PORT`/`EMAIL_USE_TLS`/`DEFAULT_FROM_EMAIL` already have sensible defaults in `render.yaml` - only override if your provider needs something different.
3. If your provider requires sender-domain verification (most do, to avoid landing in spam) - that's a step on the provider's own dashboard, tied to `wanderes.com`'s DNS, nothing in this codebase.
4. No redeploy needed for the env var change itself - the "Forgot your password?" link appears automatically once `EMAIL_HOST` is set.

### What Claude Code cannot do

Create an account with any email provider or agree to their terms - the same boundary already documented for Google OAuth and KAYAK above.

**Reference:** `users/urls.py` (the four password-reset views), `users/templates/users/password_reset_*.html/.txt`, `config/settings/base.py`'s `EMAIL_*` settings, `users/tests/test_password_reset.py`.

---

## 7. IP-Based Country Detection for Automatic Language Suggestion — ✅ RESOLVED 2026-09-05

**Decision: don't build it.** "vamos decidir a geolocalização por IP: usar só o navegador mesmo" (let's decide on IP geolocation: just use the browser, really) - option 3 of the three researched below. Automatic language detection stays exactly as already built: saved preference priority (account-level for authenticated visitors, cookie for anonymous) plus the browser's own `Accept-Language` header, with a dismissible "prefer Wanderes in X?" suggestion banner driven entirely by that signal. No IP address is ever read, sent anywhere, or stored for this feature.

**Why this was a human decision in the first place**, per `15_IMPLEMENTATION_GUIDE.md` §38: turning IP-based detection on would have meant sending every anonymous visitor's IP address somewhere new on every request (either to a third-party API in real time, or via a downloaded geolocation database requiring a new external account/license) - simultaneously "what data we collect," "whether a new technology should be introduced," and "how user privacy is interpreted." This app's footer already makes a live privacy promise to visitors ("We never store your message text or share this data with third parties") that a new third-party IP data flow wouldn't have fallen under - exactly the kind of quiet scope creep this project's human-decision boundary exists to prevent.

**What was researched (options 1 and 2, not chosen)**: a third-party HTTP geolocation API (ip-api.com, ipapi.co, ipinfo.io - simplest to integrate but sends the visitor's real IP to that company on every lookup); a downloaded offline database (MaxMind's free GeoLite2 Country `.mmdb` via Django's built-in `django.contrib.gis.geoip2` - no per-request external call, but a new MaxMind account/license key and a periodic re-download to maintain). Both rejected in favor of the browser-only signal, which the original request's own example already argued is the *more* accurate one anyway ("a visitor physically located in Portugal may still prefer English" - something IP-based country can't know but the browser's own language setting already does).

**What Claude Code did once decided**: nothing - the browser-only implementation was already complete and live (2026-09-04/05, see `DEVELOPMENT_LOG.md`). This entry just formally closes the open question so it stops appearing as a pending decision; no code, test, or documentation change was needed beyond this file and `PROJECT_STATE.md`.

**Reference:** `core/context_processors.py` (`_browser_preferred_language`, `language_suggestion`), `core/middleware.py` (`UserLanguagePreferenceMiddleware`), `core/views.py` (`set_language`), `users/models.py` (`User.preferred_language`), `core/tests/test_language_detection.py`.

---

## How to unblock

Reply with your decision(s) — even a partial one (e.g., "let's start with just a destination dataset and Anthropic Claude, defer flights/hotels") is enough to resume work. Claude Code will then:

1. Update this file (mark the decision resolved, with the date and what was chosen).
2. Update `PROJECT_STATE.md`.
3. Add a `DEVELOPMENT_LOG.md` entry.
4. Implement the corresponding adapter(s).
