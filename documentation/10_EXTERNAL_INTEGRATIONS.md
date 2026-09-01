# 10 — External Integrations

## 1. Purpose

TravelAgent depends on external services for travel information, availability, location data, booking opportunities, and AI capabilities.

External integrations must remain isolated from the core application so providers can be replaced without requiring major changes to TravelAgent's business logic.

## 2. Integration Categories

TravelAgent may integrate with:

* Flight search and availability providers.
* Hotel and accommodation providers.
* Destination and travel information providers.
* Maps and geolocation services.
* Weather and climate services.
* Booking and affiliate providers.
* AI providers.

The exact providers will be selected based on coverage, reliability, cost, licensing, and commercial requirements.

## 3. Integration Architecture

External providers should be accessed through stable internal interfaces and provider-specific adapters.

```text id="3j1f3x"
TravelAgent
     ↓
Internal Integration Interface
     ↓
Provider Adapter
     ↓
External API
```

The rest of the application should depend on the internal interface rather than directly on a specific provider.

For example, the recommendation system should request flight options through TravelAgent's flight interface without needing to know which external provider supplies the data.

This allows a provider to be replaced with minimal application changes:

```text id="6f4m2a"
TravelAgent
     ↓
Flight Provider Interface
     ↓
Provider A
```

can later become:

```text id="q7v8hx"
TravelAgent
     ↓
Flight Provider Interface
     ↓
Provider B
```

Provider-specific authentication, request formats, response formats, retries, and error handling should remain inside the corresponding adapter.

**Provider replaceability is an architectural requirement.**

## 4. External Data

External data should be treated as untrusted input.

The application should:

* Validate provider responses.
* Normalize data into internal representations where necessary.
* Handle incomplete or inconsistent results.
* Apply timeouts.
* Handle provider failures gracefully.
* Avoid exposing raw provider responses unless required.

TravelAgent should not assume that an external provider will always be available.

## 5. Provider Redundancy & Availability

TravelAgent should avoid critical single points of failure in external dependencies.

For critical capabilities, TravelAgent should aim to have at least two viable providers when technically and commercially practical.

Examples may include:

* Primary flight provider → secondary flight provider.
* Primary hotel provider → secondary hotel provider.
* Primary AI provider → secondary AI provider.

However, redundancy should not be required when maintaining a second provider would introduce disproportionate cost or complexity.

When no practical alternative exists, the system should use graceful degradation instead.

A typical fallback strategy is:

```text id="xcak1s"
Primary Provider
      ↓
   Available?
   ↙       ↘
 Yes        No
 ↓          ↓
Use it   Fallback / Cached Data
              ↓
          If unavailable
              ↓
       Graceful degradation
```

The fallback strategy should be defined according to the importance and real-time requirements of each integration.

## 6. Monitoring & Service Health

TravelAgent should monitor important external dependencies.

Monitoring should track, where applicable:

* Provider availability.
* Error rates.
* Response times.
* Rate-limit events.
* Authentication failures.
* Unexpected response changes.

Critical provider failures should generate alerts so they can be investigated before they significantly affect users.

Monitoring and fallback are separate responsibilities:

* **Monitoring** detects that a provider is failing.
* **Fallback** determines what the application does when the failure occurs.

The system should avoid repeatedly sending requests to a provider that is known to be unavailable.

## 7. Caching

Frequently requested and relatively stable external information may be cached using Redis.

Examples include:

* Destination information.
* Weather data for appropriate time periods.
* Search results with a short lifetime.
* Provider metadata.

Highly dynamic information such as real-time availability and prices should not be treated as permanently cached data.

Cache expiration should depend on the type of information.

## 8. Provider Failures

External providers may experience:

* Timeouts.
* Rate limits.
* Service outages.
* Invalid responses.
* Temporary network failures.
* Changes to their API.

TravelAgent should handle these situations without bringing down the entire application.

Where appropriate, the system may:

* Retry transient failures.
* Use cached information.
* Switch to a fallback provider.
* Return partial results.
* Explain limitations to the user.

## 9. Booking & Affiliate Providers

TravelAgent may redirect users to external booking providers.

The backend should generate or retrieve the appropriate provider link and the frontend should clearly indicate that the user is leaving TravelAgent when appropriate.

Commercial relationships must not influence recommendation quality.

A provider should not receive preferential ranking simply because TravelAgent earns a referral commission.

## 10. Credentials & Secrets

External API credentials must:

* Remain server-side.
* Never be exposed to the browser.
* Be stored using secure environment or secret-management mechanisms.
* Be rotated when necessary.
* Be separated between development and production environments.

## 11. Evolution

The first implementation should use only providers required by the MVP.

Additional providers and fallback mechanisms should be introduced based on actual reliability, business importance, cost, and usage.

The Integration Layer should make provider replacement possible without requiring major changes to TravelAgent's domain, recommendation logic, or frontend.

Changing a provider should primarily involve implementing or configuring a new adapter behind the existing internal interface.

## 13. Flight & Hotel Integration

### 13.0 Status (2026-09-01)

**Flight provider decision: ✅ made.** `DECISIONS_PENDING.md` §4 - **Duffel is the MVP flight provider**, chosen because it's the only researched option accessible without a traffic/MAU minimum TravelAgent doesn't have pre-launch (Skyscanner, KAYAK, Kiwi, and Amadeus's now-decommissioned self-serve tier all require established traffic - see §4 for the full comparison). **Not a permanent commitment** - Skyscanner, KAYAK, Amadeus Enterprise, or direct airline/NDC connections remain future options once TravelAgent has the traffic or business maturity they require; the interface below exists specifically so adding or switching to one of them later is a new adapter, not a rewrite.

**Hotels: still unresolved**, not part of this decision (Booking.com's Affiliate Partner Program was the front-runner from the original research in §4).

**Implementation status: design only, per the brief's own instructions.** The `FlightProvider` interface, `DuffelFlightProvider` adapter, normalization, recommendation-engine integration, UI, and booking flow are **not yet built** - a set of Human Review items (`DECISIONS_PENDING.md` §4, "Human Review" - the booking-flow shape, markup vs. revenue-share economics, and how much of booking/checkout the first pass actually covers) need sign-off first.

### 13.1 Internal interfaces

Following this document's §3 pattern exactly - the recommendation engine and the rest of the application depend on these interfaces, never on Duffel (or any future flight/hotel provider) directly:

```text
FlightProvider (ABC)
    search_flights(origin, destination, depart_date, return_date=None, cabin=None, passengers=1) -> list[FlightOption]
    get_flight_details(provider_reference) -> FlightOption
    build_booking_link(FlightOption) -> str   # Duffel Links checkout URL, or a future provider's affiliate/deep link

HotelProvider (ABC)
    search_hotels(destination, check_in, check_out, guests, ...) -> list[HotelOption]
    get_hotel_details(provider_reference) -> HotelOption
    build_affiliate_link(HotelOption) -> str
```

`build_booking_link` (renamed from the earlier draft's `build_affiliate_link` for flights specifically) reflects that Duffel isn't a pure affiliate redirect - see 13.6. `DuffelFlightProvider` implements `FlightProvider`; a future `SkyscannerFlightProvider`/`KayakFlightProvider` would implement the exact same interface. Selected via a `get_flight_provider()`/`get_hotel_provider()` factory reading a settings key (`FLIGHT_PROVIDER`, `HOTEL_PROVIDER`) - the same pattern already used for `ClimateProvider` (`integrations/climate/`) and `AIProvider` (`ai/provider/`): a provider swap becomes a settings change plus a new adapter, not a change anywhere else in the application (traveler profile, recommendation engine, trips, AI orchestration, chat UI all stay untouched). Provider-specific request/response shapes, auth, and error handling stay inside the adapter; nothing above the interface should ever see a raw Duffel response.

```text
                    TravelAgent
                       ↓
                FlightProvider
                       ↓
        ┌──────────────┼──────────────┐
        ↓              ↓              ↓
     Duffel       Skyscanner       KAYAK
    (MVP, now)    (future)         (future)
        ↓              ↓              ↓
        └──────────────┼──────────────┘
                       ↓
              Normalized FlightOption
                       ↓
            Recommendation Engine (deterministic scoring)
                       ↓
                  AI Explanation
                       ↓
                    User
```

### 13.2 Normalized internal representations

External providers return different shapes; the application should only ever work with its own normalized dataclasses - plain dataclasses (like `integrations.climate.MonthlyClimateSummary` and `recommendations.scoring.ScoredDestination`), not Django models. A `FlightOption` is ephemeral search-result data for one request, not persisted business data - `trips.TripFlight` already exists for a *different* concept (a flight the user has committed to as part of a saved `Trip`, manually logged with its own `rating`/`price_rate`) and should not be confused with or repurposed for live search results:

```text
FlightOption
    provider, provider_reference
    origin, destination
    departure, arrival, duration, stops
    cabin, price, currency
    airlines
    baggage_information
    booking_url                    # Duffel Links checkout URL for the MVP

HotelOption
    provider, provider_reference
    destination, name, rating
    price, currency
    room_information
    cancellation_information
    amenities
    booking_url
```

Raw provider responses should not be exposed to the rest of the application unless there is a justified reason (§4).

### 13.3 Flight search parameters: extracted, never invented

Origin, destination, dates, and passenger count are booking-critical - the AI extracts them from the conversation the same way `ai.orchestration._extract_intent()` already extracts `month`/`trip_type`/`min_temp_c` for destination recommendations (temperature=0, structured JSON schema output, never guessed - the exact pattern this session's temperature-inference bug fix reinforced), but **must never invent an airport, date, or passenger count that wasn't actually stated or clearly implied**. If any booking-critical field is missing, the application asks the traveler rather than defaulting - unlike `month` for destination recommendations (which defaults to the current month with a transparency note, since "somewhat wrong" is an acceptable degrade for a destination *suggestion*), a wrong origin airport or date is a hard failure for an actual flight search, not a soft one. This is a genuine behavioral difference from the existing destination-recommendation intent extraction and should be a separate schema/extraction path, not a naive extension of the existing one.

### 13.4 Recommendation independence from commission (reaffirmed)

§9 already establishes this; restated here because it's specifically load-bearing for this feature: **flight options must be scored on genuine fit for the traveler (price, duration, stops, departure/arrival times, traveler preferences, budget) - never boosted because Duffel's markup/commission is higher for one option than another.** The brief's own example: a traveler who values convenience should see a direct flight recommended over a cheaper one with a 9-hour layover, purely because it fits them better - regardless of which option is more profitable for TravelAgent. Scoring rules must remain deterministic and explainable, following `recommendations/scoring.py`'s existing shape exactly (hard constraints, then a scored/ranked list, with each score broken into the individual factors that produced it - see `ScoredDestination`) - a parallel `score_flights()`/`ScoredFlight` rather than folding flight logic into the destination scorer. Any markup/commission data must live structurally separate from this scoring path, the same separation already enforced between the AI reasoning layer and deterministic scoring elsewhere in the app.

### 13.5 AI responsibility boundary

The AI does not call Duffel, or any provider, itself:

```text
Django / application
       ↓
FlightProvider
       ↓
Duffel
       ↓
Normalized FlightOption results
       ↓
Recommendation engine (deterministic scoring)
       ↓
AI (explanation only)
       ↓
Traveler
```

Matches `03_SYSTEM_ARCHITETURE.md` §2.7/§3.4 exactly (AI orchestration controls what the model sees and does, but "the AI model should not directly access the database" - by extension, not external providers either) and this project's own established pattern: every AI call in `ai/orchestration.py` works over data the application already fetched and validated, never fetches anything itself. The AI's role here is understanding intent, identifying what's still missing (13.3), and explaining results - never search, ranking, or booking decisions.

### 13.6 Booking / checkout (research done, approach not yet chosen)

Duffel offers two genuinely different integration paths, not just two settings - **the choice between them is a Human Review item** (`DECISIONS_PENDING.md` §4), not something to default on:

- **Duffel Links** (low-code hosted checkout): TravelAgent generates a link via API; the traveler completes checkout on a Duffel-hosted, TravelAgent-branded page. Duffel's own marketing describes markup as configurable directly in Duffel's dashboard for this path. Minimal integration work - "no development resources needed" per Duffel.
- **Full Flights API + Duffel Payments API**: TravelAgent builds its own checkout/markup logic; Duffel acts as merchant of record so TravelAgent can charge customers without its own IATA/ARC accreditation. More integration work, full control over pricing and the purchase experience.

Either way: TravelAgent is **not** building its own payment processor, ticket issuance, or airline reservation system - both paths use Duffel's existing booking infrastructure, matching the brief's explicit boundary. The **first implementation slice may reasonably stop before booking entirely** - search, recommend, explain, and hand off to whichever Duffel flow is chosen - deferring markup/payments wiring to a later pass; this is itself one of the Human Review items.

### 13.7 Commercial model (verified where public, flagged where not)

Full detail and sourcing in `DECISIONS_PENDING.md` §4. Summary: Pay-As-You-Go plan, $3.00 per confirmed order, 1% of order value for Managed Content, $2.00 per paid ancillary, a search-to-book ratio limit ($0.005/search beyond 1,500:1), 2% on currency conversion, IATA accreditation included (Duffel's own, shared across partners). Markup mechanics differ by integration path (13.6) and were not fully reconcilable from public documentation alone - **requires confirmation with Duffel directly** before committing to a specific booking-flow implementation. Do not hard-code any commission/markup percentage that isn't confirmed.

### 13.8 Error handling

Beyond §8's general provider-failure guidance, flight search specifically needs to handle: timeouts, network failures, invalid/malformed responses, authentication failures, rate limiting, zero results, provider unavailability, and (specific to flight offers) **expired or stale offers** - a priced flight offer is only valid for a limited window and may need revalidation before booking, per Duffel's own documentation on offer expiry. The traveler should always get a useful, natural message ("We couldn't find available flights for those dates right now - try changing your dates or destination") rather than a raw exception or provider error string, consistent with `05_AI_DESIGN.md`/`ai/orchestration.py`'s existing `AIProviderError`/`ClimateProviderError` → graceful-degradation pattern.

### 13.9 Testing

Sandbox-first, per Duffel's own test/production environment split: automated tests use fixtures/mocks of Duffel responses (never live sandbox calls in the normal test suite - fast, deterministic, reproducible, independent of Duffel's actual availability), mirroring `integrations/tests/test_open_meteo.py`'s existing pattern of testing the adapter's normalization/error-handling logic against controlled inputs rather than the live API. A `DUFFEL_API_KEY` pointed at Duffel's sandbox is for manual/exploratory verification during development, not for the automated suite.

### 13.10 Affiliate & booking-flow tracking

Extends the existing `analytics` app (`Event` model, Phase 17) rather than introducing new infrastructure - candidate event types, mirroring what's already instrumented (`recommendation_generated`, `trip_created`, etc.):

- `flight_search_performed` - provider used, whether results were returned (not raw results or the traveler's actual query).
- `flight_recommendation_shown`, `flight_selected` - which normalized option, not raw provider data.
- `booking_flow_initiated` - the traveler reached Duffel's checkout (Links or the app's own, depending on 13.6).
- Actual booking/conversion tracking depends on which path 13.6 resolves to - Duffel can report confirmed orders directly for its own flow; a future pure-affiliate provider (Skyscanner, KAYAK) would rely on that provider's own postback/pixel mechanism instead, researched per-adapter when added.
- Only small structured metadata should ever be stored (provider, a reference ID, a price) - never full search queries, passenger names, or payment details, consistent with the privacy principles already applied to the existing `analytics` app. No API keys, payment information, or unnecessary personal information in logs (§10, §7.1).

### 13.11 Caching

Per §7's general principle (highly dynamic data should not be treated as permanently cached): flight prices, availability, and offer validity are exactly what that principle warns about - a cached price shown to a traveler that's no longer valid at booking time is a real trust problem for a travel consultant product, and Duffel's own offer-expiry model (13.8) makes this concrete, not hypothetical. Any caching here should be short-lived (Redis, single-digit minutes at most) and scoped to reducing duplicate identical searches in a short window, not to avoiding repeat API calls generally. PostgreSQL remains the source of truth for anything that must persist (e.g. a `Trip` the traveler actually saves) - a `FlightOption` search result itself is not persisted business data. Do not introduce caching prematurely - only once real usage patterns justify it.

### 13.12 Credentials

`DUFFEL_API_KEY` follows the exact existing pattern (`OPENAI_API_KEY` in `config/settings/base.py`/`.env.example`) - `env("DUFFEL_API_KEY", default="")`, `.env.example` documents the variable name with no real value, the real key exists only in the local `.env` (gitignored) or the deployment's secret manager (Render's `sync: false` environment variables, matching `OPENAI_API_KEY`'s existing setup). Never hard-coded, never exposed to the browser, never logged.

### 13.13 Hotels

Unresolved (13.0) - this section's detail is flights-specific per the brief that prompted it. `HotelProvider`/`HotelOption` above are sketched for interface-shape consistency with `10_EXTERNAL_INTEGRATIONS.md` §3's general pattern, not yet a concrete implementation plan the way 13.1-13.12 are for flights.

## 14. Principle

> **External providers provide capabilities and data; TravelAgent controls the business logic and user experience. Providers should be replaceable, monitored, and isolated so that external failures or provider changes do not unnecessarily disrupt the platform.**
