# 07 — API Design

## 1. Purpose

The Wanderes API is the communication boundary between the frontend and the Django backend.

It should expose product capabilities without exposing internal implementation details.

The API should be predictable, secure, and simple enough to evolve as the product grows.

## 2. API Principles

* Use resource-oriented endpoints where practical.
* Keep authentication and authorization enforced by the backend.
* Validate all client input.
* Return consistent response and error structures.
* Do not expose internal database structures unnecessarily.
* Do not expose private user data through API responses.
* Keep AI and external-provider implementation details behind the backend.
* Version the API to allow future evolution.
* Avoid creating API endpoints for functionality that Django can handle directly.

The initial API can use REST rather than introducing GraphQL or another API architecture.

## 3. Authentication & Authorization

Wanderes should initially use Django's built-in authentication and session system rather than creating a separate authentication API.

Django is responsible for:

* User authentication.
* Session management.
* Login and logout.
* Identifying the authenticated user.
* Permission checks.

API requests made by authenticated users use the Django session to identify the current user.

Conceptually:

```text
Browser
   ↓
Django Authentication
   ↓
Session Cookie
   ↓
Authenticated API Request
   ↓
Django Authorization
```

This avoids introducing JWT or a separate authentication service without a clear requirement.

If the frontend architecture changes in the future, the authentication strategy can be reconsidered.

## 4. Traveler Profile

Registered users can manage their traveler profile and preferences.

Conceptually:

```text
GET    /api/v1/profile
PATCH  /api/v1/profile

GET    /api/v1/preferences
PATCH  /api/v1/preferences
```

The API should return only information appropriate for the authenticated user.

Profile data should not expose internal AI or scoring information unless explicitly intended by the product.

## 5. Destinations & Travel Data

Destination endpoints provide travel information used by the application.

Examples:

```text
GET    /api/v1/destinations
GET    /api/v1/destinations/{id}
```

Search and filtering may be supported through query parameters.

External travel providers should remain behind the backend rather than being called directly by the frontend.

## 6. Trips

Registered users can create and manage trips.

```text
GET    /api/v1/trips
POST   /api/v1/trips
GET    /api/v1/trips/{id}
PATCH  /api/v1/trips/{id}
DELETE /api/v1/trips/{id}
```

The backend must verify ownership before returning or modifying a trip.

Trip limits for Free and Premium users are enforced by the application.

## 7. Travel History & Feedback

Travel history may be created or updated when users record previous travel experiences.

Conceptually:

```text
GET    /api/v1/travel-history
POST   /api/v1/travel-history

POST   /api/v1/feedback
GET    /api/v1/feedback
PATCH  /api/v1/feedback/{id}
```

Feedback can contain:

* Rating from 1–10.
* Positive or negative tags.
* Free-form comments.
* Relevant destination or trip.

Feedback processing that affects recommendations may be performed asynchronously.

## 8. Recommendations & AI

The recommendation API is the main entry point for Wanderes's intelligent consultant experience.

A simplified request could be:

```text
POST   /api/v1/recommendations
```

The request may contain a natural-language travel question together with optional structured requirements.

The backend then:

1. Determines the user's authorization level.
2. Builds the appropriate traveler context.
3. Retrieves relevant travel data.
4. Generates candidates.
5. Applies rules and constraints.
6. Scores candidates.
7. Uses AI for reasoning and explanation.
8. Returns the recommendation.

The frontend should not need to know how these steps are implemented internally.

For unregistered users, only the current request and permitted general travel data are used.

For registered users, authorized persistent traveler context may also be included.

## 9. Community API

Community functionality is primarily available to Premium users.

Potential endpoints include:

```text
GET    /api/v1/community/destinations/{id}/insights
GET    /api/v1/community/destinations/{id}/reviews
GET    /api/v1/community/similar-travelers
GET    /api/v1/community/travelers-at/{destination_id}
```

These endpoints must enforce Premium access where required.

Community APIs must never expose private user information merely because a user has access to community features.

## 10. Error Handling

API errors should use a consistent structure.

Conceptually:

```json
{
  "error": {
    "code": "INVALID_REQUEST",
    "message": "The travel dates are invalid."
  }
}
```

Clients should rely on stable error codes rather than parsing human-readable messages.

Common categories include:

* Authentication errors.
* Authorization errors.
* Validation errors.
* Resource-not-found errors.
* Rate-limit errors.
* External-provider errors.
* Temporary server errors.

Internal implementation details and sensitive information must not be exposed in error responses.

## 11. API Versioning

The initial API will use an explicit version:

```text
/api/v1/
```

Breaking changes should result in a new API version rather than silently changing the behavior of existing clients.

Non-breaking additions can generally remain within the existing version.

## 12. Initial Scope

The first implementation should expose only endpoints required by the actual product.

The API should not attempt to model every internal Django operation as an endpoint.

Django remains responsible for authentication, authorization, business rules, recommendation orchestration, AI integration, and external-provider communication.
