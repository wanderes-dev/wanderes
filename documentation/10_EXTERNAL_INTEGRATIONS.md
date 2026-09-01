# 10 — External Integrations

## 1. Purpose

Wanderes depends on external services for travel information, availability, location data, booking opportunities, and AI capabilities.

External integrations must remain isolated from the core application so providers can be replaced without requiring major changes to Wanderes's business logic.

## 2. Integration Categories

Wanderes may integrate with:

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
Wanderes
     ↓
Internal Integration Interface
     ↓
Provider Adapter
     ↓
External API
```

The rest of the application should depend on the internal interface rather than directly on a specific provider.

For example, the recommendation system should request flight options through Wanderes's flight interface without needing to know which external provider supplies the data.

This allows a provider to be replaced with minimal application changes:

```text id="6f4m2a"
Wanderes
     ↓
Flight Provider Interface
     ↓
Provider A
```

can later become:

```text id="q7v8hx"
Wanderes
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

Wanderes should not assume that an external provider will always be available.

## 5. Provider Redundancy & Availability

Wanderes should avoid critical single points of failure in external dependencies.

For critical capabilities, Wanderes should aim to have at least two viable providers when technically and commercially practical.

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

Wanderes should monitor important external dependencies.

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

Wanderes should handle these situations without bringing down the entire application.

Where appropriate, the system may:

* Retry transient failures.
* Use cached information.
* Switch to a fallback provider.
* Return partial results.
* Explain limitations to the user.

## 9. Booking & Affiliate Providers

Wanderes may redirect users to external booking providers.

The backend should generate or retrieve the appropriate provider link and the frontend should clearly indicate that the user is leaving Wanderes when appropriate.

Commercial relationships must not influence recommendation quality.

A provider should not receive preferential ranking simply because Wanderes earns a referral commission.

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

The Integration Layer should make provider replacement possible without requiring major changes to Wanderes's domain, recommendation logic, or frontend.

Changing a provider should primarily involve implementing or configuring a new adapter behind the existing internal interface.

## 13. Flight & Hotel Affiliate Integration (research, 2026-09-01 — not yet implemented)

Requested out of sequence, ahead of Phases 19-22, at the user's explicit direction - research and documentation only, per Phase 23's "Human Decision + Research" ownership in `15_IMPLEMENTATION_GUIDE.md`. **See `DECISIONS_PENDING.md` §4 for the full provider comparison, eligibility findings, and the pending human decision** - this section covers the technical shape the eventual implementation should take, decided in advance so the decision in §4 can move straight to implementation once made.

### 13.1 Internal interfaces

Following this document's §3 pattern exactly - the recommendation engine and the rest of the application depend on these interfaces, never on Skyscanner/KAYAK/Duffel/Booking.com directly:

```text
FlightProvider (ABC)
    search_flights(origin, destination, depart_date, return_date=None, ...) -> list[FlightOption]
    get_flight_details(provider_reference) -> FlightOption
    build_affiliate_link(FlightOption) -> str

HotelProvider (ABC)
    search_hotels(destination, check_in, check_out, guests, ...) -> list[HotelOption]
    get_hotel_details(provider_reference) -> HotelOption
    build_affiliate_link(HotelOption) -> str
```

Provider-specific adapters (`SkyscannerFlightProvider`, `DuffelFlightProvider`, `BookingComHotelProvider`, etc.) implement these behind a `get_flight_provider()`/`get_hotel_provider()` factory reading a settings key - the same pattern already used for `ClimateProvider` (`integrations/climate/`) and `AIProvider` (`ai/provider/`). Provider-specific request/response shapes, auth, and error handling stay inside the adapter; nothing above the interface should ever see a raw Skyscanner or Duffel response.

### 13.2 Normalized internal representations

External providers return different shapes; the application should only ever work with its own normalized dataclasses:

```text
FlightOption
    provider, provider_reference
    origin, destination
    departure, arrival, duration, stops
    cabin, price, currency
    baggage_information
    booking_url                    # the affiliate/deep link, or Duffel Links checkout URL

HotelOption
    provider, provider_reference
    destination, name, rating
    price, currency
    room_information
    cancellation_information
    amenities
    booking_url
```

Raw provider responses should not be exposed to the rest of the application unless there is a justified reason (§4 above).

### 13.3 Recommendation independence from commission (reaffirmed)

§9 above already establishes this; restated here because it's specifically load-bearing for this feature: **flight/hotel options must be scored on genuine fit for the traveler (price, convenience, stops, timing) - never boosted because a provider pays a higher commission.** A concrete example from the request that prompted this research: a traveler who values convenience should see the direct flight recommended over a cheaper one with a 9-hour layover, regardless of which of the two pays Wanderes more. This must live in `recommendations/scoring.py`'s existing scoring logic, structurally separated from any per-provider commission data - the same separation already enforced between the AI reasoning layer and deterministic scoring elsewhere in the app.

### 13.4 Affiliate tracking

Extends the existing `analytics` app (`Event` model, Phase 17) rather than introducing new infrastructure - candidate event types, mirroring what's already instrumented (`recommendation_generated`, `trip_created`, etc.):

- `flight_search_performed` / `hotel_search_performed` - provider used, whether results were returned (not raw results).
- `affiliate_link_generated` - already anticipated and deliberately deferred in `DECISIONS_PENDING.md` §3 ("monetization/premium and an affiliate provider don't exist in the app yet") - this research is the trigger to revisit that deferral once a provider is actually selected.
- `affiliate_link_clicked` - same.
- Provider-side conversion tracking (an actual booking happening) depends entirely on what each provider's attribution mechanism supports - Duffel can report this directly (it processes the booking); pure affiliate providers (Skyscanner, KAYAK, Booking.com) rely on their own postback/pixel mechanisms, which vary per provider and would need per-adapter research once one is selected. Only small structured metadata should ever be stored (provider, a reference ID, a price) - never full search queries or personal booking details, consistent with the privacy principles already applied to the existing `analytics` app.

### 13.5 Caching

Per §7's general principle (highly dynamic data should not be treated as permanently cached): flight/hotel prices and availability are exactly the kind of data that principle warns about - a cached price shown to a user that's no longer available at booking time is a real trust problem for a travel consultant product. Any caching here should be short-lived (Redis, likely single-digit minutes at most) and scoped to reducing duplicate identical searches in a short window, not to avoiding repeat API calls generally. Do not introduce caching prematurely - only once real usage patterns justify it.

## 14. Principle

> **External providers provide capabilities and data; Wanderes controls the business logic and user experience. Providers should be replaceable, monitored, and isolated so that external failures or provider changes do not unnecessarily disrupt the platform.**
