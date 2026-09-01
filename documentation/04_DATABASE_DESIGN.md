# 04 — Database Design

## 1. Database Design Goals

Wanderes's database must support personalization, travel planning, travel history, feedback, and community intelligence while remaining simple enough for a small team to maintain.

The database should:

* Use PostgreSQL as the source of truth for persistent business data.
* Keep user data properly isolated.
* Represent important travel concepts explicitly.
* Support personalized recommendations and traveler memory.
* Preserve useful historical information rather than overwriting it.
* Avoid storing data that has no legitimate product purpose.
* Remain compatible with Django's ORM and migrations.
* Support future growth without premature complexity.

Redis is not used as a replacement for PostgreSQL. It is reserved for temporary and performance-related workloads such as caching, rate limiting, queues, and temporary state.

## 2. Core Entities

The initial domain model will revolve around the following entities:

* **User** — account and authentication identity.
* **Traveler Profile** — persistent information about the user's travel preferences and characteristics relevant to recommendations.
* **Destination** — a place that can be recommended, visited, planned, or discussed.
* **Travel History** — records of destinations the user has actually visited.
* **Trip** — a planned or completed travel experience belonging to a user.
* **Trip Item** — individual components of a trip, such as flights, hotels, activities, or reservations.
* **Feedback** — the user's evaluation of a destination or trip, including ratings, tags, and free-form comments.
* **Preference** — structured or inferred information that helps personalize recommendations.

These entities should represent stable business concepts rather than individual screens or API responses.

## 3. Community & Collective Intelligence

Community functionality will build on user-generated travel information without exposing private user data.

Potential entities include:

* **Community Review** — a review or experience associated with a destination or travel-related entity.
* **Feedback Tag** — structured descriptions of positive or negative experiences.
* **Aggregated Insight** — anonymized and aggregated information derived from multiple users.
* **Traveler Similarity Data** — derived information used to identify meaningful patterns between travelers.

Aggregated information may influence recommendations, but individual users' private information must not be exposed through these mechanisms.

Community intelligence should be derived from sufficient aggregated data rather than relying on a single user's experience as a general truth.

## 4. Relationships

The core relationships are:

```text
User
 ├── Traveler Profile
 ├── Preferences
 ├── Travel History
 ├── Trips
 │    └── Trip Items
 └── Feedback

Destination
 ├── Travel History
 ├── Trips / Trip Items
 ├── Feedback
 └── Community Insights
```

A user may visit many destinations, and a destination may be visited by many users.

A user may have multiple trips, while each trip belongs to one user.

Feedback may be associated with a completed trip, destination, or both, depending on the type of feedback being collected.

The detailed relationship model will be refined during implementation before the final Django models are created.

## 5. Data Ownership & Privacy

Persistent user data belongs to the user's account and must be protected by application-level authorization.

The system should distinguish between:

* **Private user data** — accessible only to the user and authorized internal processes.
* **Derived user data** — preferences or insights generated from the user's activity.
* **Aggregated community data** — information combined from multiple users and suitable for collective analysis.
* **Public travel data** — information obtained from external travel or destination providers.

AI processes must receive only the data necessary for the current task.

Private user information must never be exposed to another user through recommendations, community features, or AI responses.

## 6. Indexes & Performance

PostgreSQL indexes should be introduced based on actual query patterns.

Likely candidates include:

* User identifiers.
* Destination identifiers.
* Trip ownership and status.
* Travel history by user and destination.
* Feedback by user and destination.
* Frequently queried timestamps.

Indexes should not be added indiscriminately because they increase storage and write costs.

Performance should first be measured using realistic queries before introducing more advanced database optimization.

## 7. Redis Data

Redis should contain temporary or derived data that does not need to be the permanent source of truth.

Examples include:

* Cached travel-provider responses.
* Rate-limit counters.
* Background-job queues.
* Short-lived session or workflow state.
* Temporary AI conversation state where appropriate.

If Redis data is lost, the system should remain able to recover from PostgreSQL or external providers whenever practical.

Permanent business data such as trips, travel history, feedback, and traveler profiles belongs in PostgreSQL.

## 8. Evolution & Migrations

The database will evolve through Django migrations rather than manual production schema changes.

Changes should be:

* Small and reviewable.
* Backward-compatible where practical.
* Tested before production deployment.
* Designed to preserve existing user data.

The initial schema should avoid speculative entities and fields that are not required by the product.

As Wanderes evolves, the database model can be expanded based on real product requirements and observed usage rather than attempting to predict the complete future system.
