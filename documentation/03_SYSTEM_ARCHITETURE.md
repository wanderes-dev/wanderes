# Wanderes — System Architecture

## 1. Architecture Goals & Principles

The Wanderes architecture must support the product's core objective: providing a trustworthy, personalized, and continuously improving travel consultation experience.

The architecture should be designed to support the MVP while providing clear paths for future expansion.

### 1.1 Product-Driven Architecture

The architecture must support the product requirements defined in `02_product_requirements.md`.

Technical decisions should serve the product experience rather than introduce unnecessary complexity.

The system should prioritize:

- Personalization.
- Reliability.
- Privacy.
- Explainability.
- Maintainability.
- Scalability.
- Development velocity.

### 1.2 Start Simple, Scale Deliberately

The initial architecture should be appropriate for a small development team or solo developer.

The MVP should avoid unnecessary distributed systems, microservices, and infrastructure complexity.

Components should only be separated into independent services when there is a clear technical or business reason to do so.

The architecture should nevertheless provide clear boundaries that allow components to be extracted or scaled independently in the future.

### 1.3 Modular Architecture

The system should be organized into well-defined modules with clear responsibilities.

Major domains should be separated logically, including:

- User Management.
- Traveler Profile.
- Memory.
- Travel History.
- Recommendations.
- Rules Engine.
- Scoring Engine.
- AI Orchestration.
- Travel Data.
- Feedback.
- Community Intelligence.
- Traveler Connections.
- Notifications.
- External Integrations.

These boundaries should exist even when multiple modules initially run within the same application.

### 1.4 Privacy by Design

Privacy must be an architectural requirement rather than an additional feature.

The architecture must ensure:

- Strong user-data isolation.
- Controlled access to personal information.
- Purpose-limited data usage.
- Explicit separation between private and shareable information.
- Protection of user information throughout its lifecycle.

The AI must never have unrestricted access to all user data.

AI context should be assembled according to the user's authorization and the purpose of the current interaction.

### 1.5 AI Model Independence

The application should not be tightly coupled to a single AI model or provider.

The architecture should allow AI models to be:

- Replaced.
- Upgraded.
- Evaluated.
- Combined.
- Used for different tasks.

AI providers should be accessed through an abstraction layer rather than directly throughout the application.

### 1.6 Deterministic Business Logic

Important business decisions should not depend entirely on probabilistic AI behavior.

Where appropriate, deterministic components should control:

- Business rules.
- Eligibility.
- Data validation.
- Recommendation constraints.
- Safety requirements.
- User permissions.
- Subscription limits.
- Scoring factors.

AI should provide intelligence and interpretation while deterministic systems enforce important boundaries.

### 1.7 Explainability

The architecture must preserve the information required to explain important recommendations.

A recommendation should be traceable to relevant factors such as:

- Traveler preferences.
- Travel history.
- Explicit constraints.
- Recommendation rules.
- Scores.
- External information.
- Community insights, when applicable.

The system should avoid producing recommendations that cannot be meaningfully explained.

### 1.8 External Integration Isolation

External travel providers and data sources should be isolated behind integration interfaces.

The core Wanderes system should not depend directly on the implementation details of a specific provider.

This allows providers to be:

- Added.
- Removed.
- Replaced.
- Compared.

without requiring major changes to the core recommendation system.

### 1.9 Data as a Product Asset

Traveler data, feedback, and travel history are important sources of product intelligence.

However, data must be treated as an asset that requires strict privacy and security controls.

The architecture should distinguish between:

- Private user data.
- User-approved shareable data.
- Aggregated community data.
- External provider data.
- Derived recommendation data.

These categories must not be treated as interchangeable.

### 1.10 Future Community Intelligence

The MVP should primarily focus on individual personalization.

The architecture should nevertheless allow future community intelligence to be introduced without redesigning the entire platform.

Community intelligence should operate primarily on appropriate aggregated or privacy-preserving data rather than directly exposing individual user information.

### 1.11 Observability

The system should provide sufficient observability to understand:

- Application health.
- AI behavior.
- Recommendation performance.
- External integration failures.
- Security events.
- System performance.
- User-facing errors.

Observability data must itself follow Wanderes's privacy requirements.

### 1.12 Evolution Over Time

The architecture should support the evolution of Wanderes from:

MVP → Growing Platform → Full Wanderes Ecosystem

without requiring a complete rewrite at each stage.

However, future scalability requirements should not justify unnecessary complexity in the MVP.

Architectural complexity should be introduced only when the product demonstrates a need for it.

                    Wanderes
                         │
                    Django / API
                         │
          ┌──────────────┼──────────────┐
          │              │              │
      PostgreSQL       Redis          AI Layer
          │              │              │
     Persistent       Cache /       AI Providers
       Data           Queues
                         │
                  Background Jobs
                         │
                  External APIs


## 2. High-Level Architecture

Wanderes will use a modular application architecture centered around a Django-based backend.

The initial system should remain simple enough to be developed and operated by a small team or solo developer while maintaining clear boundaries between major domains.

### 2.1 Architectural Overview

The initial architecture consists of the following major components:

- Client Applications
- API Layer
- Application Layer
- Domain Services
- AI Orchestration Layer
- Data Layer
- Caching and Background Processing
- External Travel Integrations
- Observability and Security

The initial implementation may run as a modular monolithic application rather than multiple independent services.

### 2.2 High-Level Architecture


                        ┌─────────────────────┐
                        │   Client Apps       │
                        │                     │
                        │ Web / Mobile        │
                        └──────────┬──────────┘
                                   │
                                   ▼
                        ┌─────────────────────┐
                        │      API Layer      │
                        │                     │
                        │ Authentication      │
                        │ Authorization       │
                        │ Request Validation  │
                        └──────────┬──────────┘
                                   │
                                   ▼
                  ┌─────────────────────────────────┐
                  │       Application Layer         │
                  │                                 │
                  │ User Management                 │
                  │ Traveler Profile                │
                  │ Trips                           │
                  │ Feedback                        │
                  │ Recommendations                 │
                  │ Community                       │
                  └───────────────┬─────────────────┘
                                  │
                  ┌───────────────┼────────────────┐
                  │               │                │
                  ▼               ▼                ▼
        ┌────────────────┐ ┌──────────────┐ ┌───────────────┐
        │ AI Orchestration│ │ Rules Engine │ │ Scoring Engine│
        │     Layer       │ │              │ │               │
        └────────┬────────┘ └──────┬───────┘ └───────┬───────┘
                 │                 │                 │
                 └─────────────────┼─────────────────┘
                                   │
                                   ▼
                         ┌───────────────────┐
                         │    Data Layer     │
                         │                   │
                         │ PostgreSQL        │
                         │ Redis             │
                         └─────────┬─────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    │                             │
                    ▼                             ▼
          ┌──────────────────┐          ┌──────────────────┐
          │ Background Jobs  │          │ External Travel  │
          │                  │          │ Integrations     │
          │ Async Processing │          │                  │
          │ Data Sync        │          │ Flights          │
          │ AI Tasks         │          │ Hotels           │
          └──────────────────┘          │ Destinations     │
                                        └──────────────────┘                  



### 2.3 Client Applications

The client layer is responsible for presenting the Wanderes experience to users.

The architecture should allow multiple clients to use the same backend services.

Potential clients include:

- Web application.
- Mobile applications.
- Future additional interfaces.

Clients should not contain core business logic that must remain consistent across platforms.

### 2.4 API Layer

The API layer provides a controlled interface between client applications and the backend.

Its responsibilities include:

- Authentication.
- Authorization.
- Request validation.
- Response formatting.
- Rate limiting.
- API versioning.
- Error handling.

The API layer should not contain complex recommendation or AI logic.

### 2.5 Application Layer

The application layer coordinates user actions and business workflows.

Examples include:

- Creating a traveler profile.
- Updating preferences.
- Recording travel history.
- Requesting recommendations.
- Creating a trip.
- Submitting feedback.
- Accessing community information.

The application layer coordinates the relevant domain services rather than implementing every domain rule itself.

### 2.6 Domain Services

Domain services contain the core Wanderes business capabilities.

Important domains include:

- Traveler Profile.
- Memory.
- Travel History.
- Trips.
- Recommendations.
- Feedback.
- Rules.
- Scoring.
- Community Intelligence.
- Traveler Connections.

Each domain should have clear responsibilities and controlled access to other domains.

### 2.7 AI Orchestration Layer

The AI orchestration layer controls how AI models are used by Wanderes.

It should be responsible for:

- Selecting the appropriate AI capability.
- Building AI context.
- Retrieving relevant traveler information.
- Controlling what information is exposed to the model.
- Managing prompts and structured instructions.
- Processing model responses.
- Validating AI output.
- Handling model failures.
- Supporting multiple AI providers.

The AI model should not directly access the database.

### 2.8 Rules and Scoring

The Rules Engine and Scoring Engine should remain separate from the AI layer.

The Rules Engine should enforce deterministic constraints and business rules.

The Scoring Engine should evaluate destinations, hotels, flights, and other options using defined factors.

AI may assist in interpreting information, but important business constraints should remain deterministic whenever possible.

### 2.9 Data Layer

PostgreSQL will be the primary persistent data store.

It will contain structured application data such as:

- Users.
- Traveler profiles.
- Preferences.
- Travel history.
- Trips.
- Feedback.
- Recommendations.
- Community data.
- System configuration.

Redis will provide supporting infrastructure capabilities such as:

- Caching.
- Temporary state.
- Rate limiting.
- Background job queues.

Redis should not replace PostgreSQL as the system of record for persistent business data.

### 2.10 Background Processing

Long-running or asynchronous operations should be handled outside the normal request-response cycle.

Potential background tasks include:

- AI processing.
- External data synchronization.
- Recommendation calculations.
- Community aggregation.
- Notifications.
- Scheduled maintenance.

Redis may be used as part of the background processing infrastructure.

### 2.11 External Travel Integrations

External providers should be accessed through dedicated integration modules.

Examples include:

- Flight providers.
- Hotel providers.
- Destination data providers.
- Maps and geographic services.
- Weather services.
- Other travel-related APIs.

External provider responses should be normalized before being used by the core Wanderes system.

This prevents provider-specific formats from spreading throughout the application.

### 2.12 Observability and Security

Observability and security capabilities should operate across the architecture.

The system should provide:

- Structured logging.
- Application monitoring.
- Error tracking.
- Performance monitoring.
- Security event logging.
- Authentication monitoring.
- External API monitoring.

Sensitive traveler information must not be unnecessarily exposed through logs, metrics, or monitoring systems.

### 2.13 Architectural Evolution

The initial implementation should remain a modular monolith.

As Wanderes grows, individual components may be extracted into independent services when justified by:

- Performance requirements.
- Independent scaling requirements.
- Operational isolation.
- Team ownership.
- Reliability requirements.
- Business requirements.

The architecture should therefore prioritize strong internal boundaries before introducing distributed infrastructure.
## 3. Architectural Layers & Responsibilities

Wanderes will use clearly defined architectural layers to separate user interaction, application workflows, core business logic, AI capabilities, infrastructure, and external integrations.

The purpose of these layers is to keep the system organized, understandable, maintainable, and easy to evolve.

### 3.1 Presentation Layer

The Presentation Layer is responsible for communication between Wanderes and the user.

It receives requests from the web or mobile application and returns responses.

Responsibilities include:

- Receiving user requests.
- Validating request structure.
- Authentication.
- Authorization.
- Returning responses.
- Returning errors in a consistent format.

The Presentation Layer should not contain Wanderes's core business logic.

For example, it should not decide which destination is best for a traveler.

### 3.2 Application Layer

The Application Layer coordinates the actions required to complete a user request.

For example, when a registered user asks for a personalized destination recommendation, the Application Layer may:

1. Identify the user.
2. Check the user's permissions and subscription.
3. Retrieve the relevant traveler information.
4. Request recommendations.
5. Store the result when necessary.
6. Return the response to the user.

The Application Layer coordinates these operations but should not contain all of the underlying business rules.

### 3.3 Domain Layer

The Domain Layer contains the core concepts and business rules of Wanderes.

Examples include:

- Traveler preferences.
- Traveler memory.
- Travel history.
- Trip rules.
- Recommendation rules.
- Scoring.
- Feedback.
- Subscription limitations.
- Community intelligence.

For example:

If a traveler has already visited Paris, the system may decide that Paris should normally not be recommended again.

This is a Wanderes business rule and therefore belongs to the domain logic rather than the user interface or AI provider.

### 3.4 AI Layer

The AI Layer provides artificial intelligence capabilities to Wanderes.

The AI may be responsible for tasks such as:

- Understanding natural language.
- Extracting traveler preferences.
- Understanding free-form feedback.
- Generating natural responses.
- Interpreting travel information.
- Supporting recommendation reasoning.

The AI should not be responsible for enforcing critical business rules by itself.

For example, the AI should not independently decide whether a user is allowed to access a Premium feature.

Deterministic application and domain logic should enforce such rules.

### 3.5 Infrastructure Layer

The Infrastructure Layer provides the technical services required by the application.

Examples include:

- PostgreSQL.
- Redis.
- Background job processing.
- File storage.
- Email services.
- Logging.
- Monitoring.

The core Wanderes logic should not be tightly coupled to a specific infrastructure implementation when avoidable.

### 3.6 Integration Layer

The Integration Layer communicates with external services and providers.

Examples include:

- Flight APIs.
- Hotel APIs.
- Destination data providers.
- Maps providers.
- Weather providers.
- Payment providers.
- AI providers.
- Affiliate or referral providers.

External provider-specific formats should be converted into Wanderes's internal formats before being used by the core application.

This prevents external providers from becoming tightly coupled to Wanderes's internal business logic.

### 3.7 Dependency Direction

The general dependency flow should be:

```text
User
  ↓
Presentation Layer
  ↓
Application Layer
  ↓
Domain Layer
  ↓
Infrastructure / Integrations
```

AI capabilities may be used by the Application and Domain layers through controlled interfaces.

External providers and infrastructure should not directly control Wanderes's business logic.

### 3.8 Architectural Principle

Each layer should have a clear responsibility.

The system should avoid placing unrelated responsibilities into the same layer simply because it is convenient.

The objective is not to create unnecessary complexity.

The objective is to ensure that each part of Wanderes has a clear purpose and can evolve without unnecessarily affecting the rest of the system.               

## 4. Data Architecture

Wanderes will use PostgreSQL as its primary persistent database and Redis as a supporting infrastructure component.

The data architecture must prioritize reliability, privacy, clear ownership, and the ability to scale as the platform grows.

### 4.1 PostgreSQL

PostgreSQL will be the primary system of record for Wanderes.

It will store persistent application data, including:

- User accounts.
- Traveler profiles and preferences.
- Travel history.
- Trips.
- Feedback.
- Recommendations.
- Subscription information.
- Community data.
- Application configuration.

PostgreSQL will remain the authoritative source for persistent business data.

### 4.2 Redis

Redis will be used for temporary or performance-related workloads rather than permanent business data.

Potential uses include:

- Caching.
- Rate limiting.
- Background job queues.
- Temporary conversation or processing state.

Redis must not be used as the primary source of truth for important traveler or business data.

### 4.3 Data Ownership

Each major domain should have clear ownership of its data.

For example:

- Traveler Profile owns traveler preferences.
- Travel History owns completed trips.
- Feedback owns submitted feedback.
- Trips owns planned trips.
- Subscription Management owns subscription status.

Other components may use this information through controlled application interfaces rather than directly modifying another domain's data.

### 4.4 User Data Isolation

Traveler data must be isolated between users.

The system must ensure that:

- One user cannot access another user's private information.
- AI requests only receive authorized user information.
- Community features use only information that is permitted for sharing or appropriately aggregated.
- Internal systems follow the same access restrictions as user-facing features.

### 4.5 Persistent vs Temporary Data

The system should distinguish between information that must be permanently stored and information that only needs to exist temporarily.

Persistent data belongs in PostgreSQL.

Temporary data may use Redis or other appropriate temporary storage.

The system should avoid storing information permanently when it has no legitimate purpose for the Wanderes experience.

### 4.6 Data Architecture Principles

The data architecture should follow these principles:

- PostgreSQL is the source of truth for persistent business data.
- Redis supports performance and temporary workloads.
- Personal data is isolated and access-controlled.
- Data is stored only for legitimate product purposes.
- Sensitive information is not unnecessarily duplicated.
- Data structures should support future personalization and community intelligence without compromising user privacy.

## 6. Integrations & Background Processing

Wanderes depends on external travel providers and background processing for tasks that should not block the main user request.

### 6.1 External Integrations

External services are accessed through the Integration Layer rather than directly from business logic.

Typical integrations may include:

* Flight search and availability providers.
* Hotel and accommodation providers.
* Destination and travel information providers.
* Maps and location services.
* External booking or affiliate providers.
* AI model providers.

External integrations should be isolated behind clear interfaces so providers can be replaced without changing core application logic.

The application must treat external data as untrusted input and handle provider failures, timeouts, incomplete results, and changing APIs gracefully.

### 6.2 Background Processing

Background processing is used for tasks that do not need to complete during the user's immediate request.

Examples include:

* Updating cached travel data.
* Processing post-trip feedback.
* Updating aggregated community intelligence.
* Sending notifications or reminders.
* Performing scheduled data synchronization.
* Processing other non-urgent tasks.

Redis will support the background job mechanism and temporary task state.

The initial implementation should use a simple Django-compatible background task approach rather than introducing a separate distributed processing architecture.

### 6.3 Integration Principles

Integrations should follow these principles:

* Keep provider-specific logic isolated.
* Define clear timeouts and failure handling.
* Avoid making external calls when cached or existing data is sufficient.
* Do not make critical business decisions dependent on a single external provider.
* Never expose provider credentials to clients.
* Log integration failures without storing unnecessary sensitive data.
* Make background jobs safe to retry where practical.

Background processing should improve performance and reliability without becoming a separate architectural layer or service unless future scale genuinely requires it.

## 7. Security, Scalability & Evolution

Security, privacy, and controlled growth are core architectural concerns. The initial system should remain simple while establishing boundaries that allow Wanderes to scale safely.

### 7.1 Security & Privacy

Wanderes must protect user data throughout the application.

Key principles:

* Authentication and authorization are enforced by the application.
* Users can only access data they are authorized to access.
* AI components receive only the user information required for the current task.
* Sensitive data is not exposed to external providers unless necessary.
* API credentials and secrets are stored securely and never exposed to clients.
* External input is validated before being used by the application.
* Rate limiting is applied to protect public endpoints and AI resources.
* Logs should avoid unnecessary personal or sensitive information.

Privacy requirements defined in the Product Requirements are treated as architectural constraints rather than optional features.

### 7.2 Scalability

The initial architecture is designed to scale vertically and horizontally without requiring an immediate transition to microservices.

The first scaling strategies should be:

* Optimize database queries and indexes.
* Use Redis for caching and temporary workloads.
* Move expensive work to background processing.
* Use external services through replaceable integration interfaces.
* Scale application instances horizontally when necessary.
* Monitor system performance before introducing additional infrastructure.

PostgreSQL remains the source of truth as the system grows.

### 7.3 Evolution of the Architecture

Wanderes will initially remain a modular monolith.

If the system grows significantly, individual components may eventually be separated into independent services when there is a clear technical or organizational reason.

Possible candidates could include:

* AI processing.
* Recommendation processing.
* Community intelligence processing.
* High-volume external data synchronization.

Such separation should only happen when the benefits outweigh the additional operational complexity.

The architecture should therefore favor **clear module boundaries inside one application first**, making future extraction possible without prematurely operating a distributed system.

### 7.4 Architectural Principle

The architecture should evolve according to actual product and scale requirements.

> **Start simple, maintain clear boundaries, measure real problems, and introduce complexity only when it solves a demonstrated problem.**

