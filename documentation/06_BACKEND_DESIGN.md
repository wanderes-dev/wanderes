# 06 — Backend Design

## 1. Purpose

This document defines how the TravelAgent backend is organized inside the Django application.

The goal is to keep the system maintainable as a modular monolith while supporting future growth.

## 2. Backend Principles

* Keep business logic separate from infrastructure concerns.
* Prefer clear modules over deeply coupled code.
* Keep AI provider logic isolated from travel business logic.
* Use PostgreSQL as the source of truth.
* Use Redis only for temporary and performance-related workloads.
* Avoid premature microservices.
* Design modules so they can be extracted later if necessary.

## 3. Core Modules

### Authentication

Responsibilities:

* Registration
* Login
* User identity
* Permissions
* Account management

### Traveler Profiles

Responsibilities:

* Traveler preferences
* Traveler memory
* Profile updates
* Preference management

### Destinations

Responsibilities:

* Destination data
* Destination search
* Destination attributes
* Destination information

### Trips

Responsibilities:

* Trip creation
* Trip management
* Trip history
* Trip items

### Feedback

Responsibilities:

* Ratings
* Feedback tags
* Free-form feedback
* Preference updates

### Recommendations

Responsibilities:

* Candidate generation
* Recommendation scoring
* Recommendation orchestration
* Recommendation explanations

### Community Intelligence

Responsibilities:

* Community reviews
* Aggregated insights
* Similar-traveler signals
* Community statistics

### AI

Responsibilities:

* AI orchestration
* Prompt construction
* Context preparation
* Provider abstraction

### Integrations

Responsibilities:

* Travel providers
* External APIs
* Affiliate providers
* Third-party services

## 4. Request Flow

A typical recommendation request:

```text
Client
  ↓
API Endpoint
  ↓
Application Service
  ↓
Recommendation Module
  ↓
Travel Data + Traveler Context
  ↓
AI Module
  ↓
Response
```

Business workflows should be coordinated by application services rather than controllers or database models.

## 5. Background Jobs

Background jobs should handle:

* Feedback processing
* Community insight updates
* Data synchronization
* Notifications
* Cache refreshes

User-facing requests should remain fast and avoid long-running processing.

## 6. API Strategy

The frontend should communicate with the backend through a versioned API.

Initial goals:

* Consistent response formats
* Clear authentication boundaries
* Predictable error handling
* Separation between internal services and public APIs

The exact API specification will be defined in a later document.

## 7. Evolution

New features should be added as modules rather than mixed into existing code.

When a module becomes independently scalable or operationally complex, it may be considered for extraction into a separate service.

Until then, TravelAgent remains a modular monolith.
