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

### 13.6 Flight interface scaffolded ahead of KAYAK access (2026-09-02)

Per direct request ("leave it ready to receive a flight source from KAYAK, so implementing it later is all that's left") - the §13.1/§13.2 interface shape above is now real code, not just documentation, implemented exactly as described there:

- `integrations/flights/base.py` - `FlightProvider` (ABC: `search_flights()`, `get_flight_details()`, `build_affiliate_link()`) and `FlightOption` (the normalized dataclass), matching this section's already-documented shape field-for-field. `FlightOption` deliberately carries no commission/payout field - a structural guard keeping §13.3's "never score by commission" principle out of reach of accidental violation, not just a prompt-level rule.
- `integrations/flights/__init__.py` - `get_flight_provider()` factory reading `settings.FLIGHT_PROVIDER`, same pattern as `integrations.climate.get_climate_provider()`/`ai.provider.get_ai_provider()`.
- `integrations/flights/kayak.py` - registered as the `"kayak"` provider, but a **deliberate skeleton, not a working adapter**: every method raises `NotImplementedError` with a message pointing back to `DECISIONS_PENDING.md` §4. KAYAK's real request/response shapes aren't publicly documented pre-approval, so guessing at them and shipping code that looks done but silently wouldn't work was rejected in favor of failing loudly and honestly. Once real API access/docs exist, filling in these three methods is the only code change needed anywhere in the app - nothing else will ever depend on this class directly, only on the `FlightProvider` interface.
- Not wired into the AI orchestration pipeline, `recommendations/scoring.py`, or any UI - the request was to "receive a source," not to consume one yet. Wiring real flight results into recommendations/chat is separate work for once `kayak.py` actually works, matching the existing "no placeholder flight/hotel UI with nothing real behind it" principle from the 2026-09-01 UX passes.
- 6 new tests (`integrations/tests/test_flights.py`): the factory's unset/unknown/valid-provider paths, and that all three `KayakFlightProvider` methods raise `NotImplementedError` rather than silently succeeding.

### 13.7 Hotel interface scaffolded ahead of Booking.com access (2026-09-04)

Per direct request ("prepare our project to receive the booking affiliate API for accommodations") - mirrors §13.6's flight scaffolding exactly, for the provider that research (`DECISIONS_PENDING.md` §4) already named as "the most promising hotel option for Wanderes's current stage":

- `integrations/hotels/base.py` - `HotelProvider` (ABC: `search_hotels()`, `get_hotel_details()`, `build_affiliate_link()`) and `HotelOption` (the normalized dataclass), matching this section's §13.1/§13.2 already-documented shape field-for-field. `HotelOption` deliberately carries no commission/payout field - the same structural guard already applied to `FlightOption`, keeping §13.3's "never score by commission" principle out of reach of accidental violation.
- `integrations/hotels/__init__.py` - `get_hotel_provider()` factory reading `settings.HOTEL_PROVIDER`, same pattern as `integrations.flights.get_flight_provider()`.
- `integrations/hotels/booking_com.py` - registered as the `"booking_com"` provider, but a **deliberate skeleton, not a working adapter**: every method raises `NotImplementedError` with a message pointing back to `DECISIONS_PENDING.md` §4. Booking.com's Affiliate Partner Program is application-reviewed - approved partners get a real XML feed, but its exact shape isn't public before approval, so guessing at it and shipping code that looks done but silently wouldn't work was rejected in favor of failing loudly and honestly, exactly as `kayak.py` already does. Once real API access/documentation exists, filling in these three methods is the only code change needed anywhere in the app - nothing else will ever depend on this class directly, only on the `HotelProvider` interface.
- Not wired into the AI orchestration pipeline, `recommendations/scoring.py`, or any UI, for the same reason as the flight scaffolding - "receive a source," not "consume one yet."
- 6 new tests (`integrations/tests/test_hotels.py`), identical shape to `test_flights.py`: the factory's unset/unknown/valid-provider paths, and that all three `BookingComHotelProvider` methods raise `NotImplementedError` rather than silently succeeding.

### 13.8 Booking.com affiliate partnership initiated via CJ Affiliate (2026-09-06)

**Documentation only - nothing in this section is implemented.** Direct user update: Wanderes has started the partnership process with Booking.com through **CJ Affiliate**, a third-party affiliate network - not a direct relationship with Booking.com.

**Program details on file:**

- Program: Booking.com Spain & Portugal
- CJ Advertiser ID: `4347393`
- Category: Hotel
- Currency: EUR
- Base commission currently displayed: 4%
- Displayed reference period: 1 day
- Deep linking: allowed

The program also displays separate commission structures for other product lines (cars, attractions, airport taxis, flights) - not evaluated or pursued here. This entry covers the Hotel/accommodation line only, matching Wanderes's actual current scope (`HotelProvider`, §13.7).

**Intended flow** (product decision, matching the "pure affiliate redirect" architecture already identified as the front-runner in `DECISIONS_PENDING.md` §4 - not the Duffel-style hosted-checkout model; Wanderes never becomes a merchant of record or handles payment):

1. The user talks to Wanderes and states destination, dates, budget, and preferences.
2. Wanderes identifies real, relevant accommodations.
3. The app's own ranking/recommendation logic scores them (same "never rank by commission" principle as §13.3 and §14 below).
4. The AI explains why a given accommodation fits.
5. Wanderes shows relevant details - property, location, price, availability - only when actually available from an authorized data source.
6. The user clicks something like "View accommodation."
7. The user is redirected to Booking.com via a trackable affiliate/deep link.
8. Booking.com owns the booking and the payment - Wanderes never processes either.
9. Wanderes may earn a commission if the transaction meets the affiliate program's conditions.

The commission or business relationship must never influence recommendation ranking - the traveler's own interest stays the deciding criterion, same as every other provider in this document.

**Restrictions noted from the CJ program terms** (not exhaustive legal advice - recorded so any future implementation is built against them from day one, not retrofitted): Booking.com brand/trademark usage; no paid search/SEM campaigns bidding on Booking.com's own branded keywords; no incentivized traffic; restrictions on software/browser extensions/similar tools that redirect or inject affiliate links; restricted sub-affiliate arrangements; social media usage rules; restrictions on what counts as acceptable content/site context for placing these links; no presenting unauthorized discounts, vouchers, or benefits alongside a listing. None of this is implemented yet, so none of it is currently at risk.

**CJ Affiliate is not the same thing as Booking.com's Demand API - this distinction must not be conflated:**

- **CJ Affiliate** - the partnership, tracking, deep links, and commission attribution described above. This is what has actually been set up so far.
- **Booking.com Demand API** - separate, programmatic access to real property/availability/pricing data. Approval into the CJ affiliate program is **not** automatic authorization for the Demand API - these are two different applications/relationships with Booking.com.

**Before implementing any real accommodation search using Booking.com data**, confirm separately whether Wanderes has been granted Demand API access and which endpoints/credentials are actually available - the same "don't guess at an undocumented shape" discipline already applied to `integrations/hotels/booking_com.py`'s `NotImplementedError` skeleton (§13.7). Do not scrape Booking.com, and do not fabricate prices, availability, or properties, regardless of what CJ access alone would technically make possible to attempt.

**Future architecture** (unchanged from what's already scaffolded in §13.7 - `HotelProvider`/`HotelOption`) keeps this replaceable, conceptually:

```
AccommodationProvider
  -> search_accommodations(...)
  -> NormalizedAccommodationOffer
  -> Wanderes recommendation/ranking
  -> AI explanation
  -> outbound affiliate/deep link
```

Booking.com should remain just one of possibly several providers behind this interface, never a hardcoded assumption.

**Status update, same day (2026-09-06): application submitted, still pending.** The Wanderes CJ Affiliate account itself is created and configured, and a formal application was submitted for the program above. Current state:

- **Application status: pending / awaiting Booking.com's manual review.** CJ itself confirmed Booking.com approves publishers manually and will follow up if/when Wanderes is approved - there is no instant-approval path here.
- **Intended model confirmed as affiliate/outbound referral** - matching the flow already documented above, not a hosted-checkout or reseller model.
- CJ also surfaced several creative resources already available under this program's listing, before approval is even granted: **WIDGET: Accommodations** (resource ID `17323139`), **WIDGET: Flights** (`17323141`), **WIDGET: Car Rentals** (`17323142`), plus evergreen links and other Booking.com creatives. **Their visibility in the CJ dashboard is not authorization to use them** - the application is still pending, and nothing here should be treated as go-ahead to embed any of these until approval actually comes through.
- **Separately tested: the Booking.com Affiliate Partner Centre itself.** Logging in returned *"You have no access rights to the Affiliate Partner Centre. Contact your administrator to request access rights."* This is a concrete, confirmed data point (not an assumption): **the CJ account does not automatically grant Affiliate Partner Centre access**, and by extension **Wanderes does not currently have confirmed access to the Booking.com Demand API** - reinforcing, with direct evidence now, the CJ-Affiliate-vs-Demand-API distinction above. Do not assume CJ approval will imply Demand API access; do not implement real Demand API calls without officially confirmed credentials/authorization; do not scrape Booking.com; do not fabricate properties, prices, or availability.
- **Per direct instruction: the pending application does not block product development elsewhere.** The accommodation architecture stays provider-decoupled (`AccommodationProvider` abstraction above) precisely so Booking.com can be wired in later - or swapped for another provider - without touching core recommendation logic.

**Status update (2026-09-09): a real CJ token provided, a real (not skeleton) CJ Link Search adapter built - `integrations/hotels/booking_com.py` still untouched.** The user provided a real CJ personal access token (`CJ_API_TOKEN`, saved to `.env`/`.env.example`/`config/settings/base.py`, never committed). Direct request: also create a model for real affiliate links. Investigated CJ's own developer documentation live (`developers.cj.com`, not guessed at) before writing any client code - same "don't guess at an undocumented shape" discipline already applied to `kayak.py`/`booking_com.py`.

**What this actually is, and what it is NOT**: CJ's own Link Search API (`GET https://link-search.api.cj.com/v2/link-search`, Bearer-token auth, publisher-only, 25 calls/minute) discovers real, currently-active, trackable affiliate links by keyword/advertiser/country - independent of Booking.com's own Demand API. This is genuinely usable now, but it is **not** property-level search: it cannot tell Wanderes which specific hotel, room, or price is available - only that a real, trackable link exists for a given advertiser/keyword match. The Demand-API-vs-CJ-API distinction above is unchanged and still the operative constraint.

**Built**: a new `integrations/affiliates/` interface (`AffiliateNetworkProvider` ABC, `AffiliateLinkResult` dataclass - carries no commission figure, same structural guard as `HotelOption`/`FlightOption`) and `CJAffiliateProvider`, a real (not skeleton) adapter implementing the documented request shape. Deliberately its own interface, not folded into `HotelProvider.build_affiliate_link()` - that method still needs a real `HotelOption`, which still needs `search_hotels()`, which still needs Demand API access. This is the natural building block for that method once `search_hotels()` also becomes real, not a replacement for it. A new `AffiliateLink` model (`integrations/models.py` - the first model this app has ever needed, since every other adapter in it is stateless) persists real links CJ's API actually returned - never fabricated. A new `CJ_WEBSITE_ID` setting (a separate credential from `CJ_API_TOKEN`, required by CJ's own API) is still unset - `CJAffiliateProvider` raises a clear `ImproperlyConfigured` error rather than making an incomplete call, same discipline as every other provider adapter in this app.

**One real unresolved uncertainty, flagged rather than papered over**: CJ's own documented sample response shows a `<link><link>...</link>...</link>` structure that looks like a documentation rendering artifact, inconsistent with the same page's own field-by-field table. The parser handles both shapes defensively, but this has not been exercised against one real live response (no `CJ_WEBSITE_ID` was available while building it) - verify against a real call before trusting it for anything user-facing.

**Still not wired into anything traveler-facing** - not `recommendations/scoring.py`, not the AI orchestration pipeline, not any template. Same "receive a source, not consume one yet" staging already applied to Kayak/Booking.com. 22 new tests (adapter, factory, model, service layer - all mocked HTTP, no live calls made), 1 new migration, `ruff check .` clean.

`integrations/hotels/booking_com.py` itself is still exactly the deliberate `NotImplementedError` skeleton it already was (§13.7) - untouched by any of this. Real property-level search still waits until the CJ application is approved **and** Demand API access/credentials are separately, officially confirmed (see `DECISIONS_PENDING.md` §4).

## 14. Principle

> **External providers provide capabilities and data; Wanderes controls the business logic and user experience. Providers should be replaceable, monitored, and isolated so that external failures or provider changes do not unnecessarily disrupt the platform.**
