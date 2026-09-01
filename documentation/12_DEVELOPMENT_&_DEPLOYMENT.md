# 12 — Development & Deployment

## 1. Purpose

This document defines how Wanderes is developed, configured, tested, and deployed.

The initial operational setup should remain simple and reproducible while supporting the services required by the application.

## 2. Development Environment

The local development environment should provide:

* Django application.
* PostgreSQL database.
* Redis.
* Background worker.
* Access to configured AI and travel providers.

The environment should be easy to start, reset, and reproduce on another development machine.

## 3. Docker

Docker should be used to simplify local development and provide consistent service environments.

The initial Docker setup should contain only the services that are actually required.

Conceptually:

```text id="f1v2az"
Docker Environment
 ├── Django
 ├── PostgreSQL
 └── Redis
        ↓
   Background Worker
```

Docker Compose can be used to coordinate these services during development.

Kubernetes and other container orchestration platforms are not required initially.

## 4. Project Structure

The Django project should follow the modular architecture defined in the system architecture documents.

Application modules should be organized around business responsibilities rather than creating one large Django application.

The exact directory structure should be finalized during implementation.

The structure should make it clear where to find:

* Domain logic.
* Application services.
* API endpoints.
* AI orchestration.
* Integrations.
* Database models.
* Background jobs.

## 5. Environment Configuration

Configuration that differs between environments must not be hardcoded.

Examples include:

* Database credentials.
* Redis configuration.
* Django secret key.
* AI provider credentials.
* Travel API credentials.
* OAuth credentials.
* Affiliate provider credentials.
* Debug settings.
* Allowed hosts.

Environment variables or an appropriate secret-management mechanism should be used.

Secrets must never be committed to source control.

## 6. Development, Staging & Production

Wanderes should separate environments:

```text id="g8zqv6"
Development
    ↓
Staging
    ↓
Production
```

**Development** is used for local implementation and experimentation.

**Staging** should reproduce the production environment closely enough to validate important changes before release.

**Production** serves real users and must use production credentials, secure configuration, backups, and monitoring.

The initial project may delay a dedicated staging environment until it provides meaningful value.

## 7. Background Workers

Background processing should run separately from the main Django request process.

The worker will process tasks such as:

* Feedback processing.
* Community insight updates.
* Data synchronization.
* Notifications.
* Cache refreshes.

Redis will support communication and temporary task state for the background processing system.

Background jobs should be designed to handle retries safely where practical.

## 8. AI & External Provider Configuration

AI and external travel providers should be configured through environment-specific credentials and settings.

The application should allow provider configuration to change without modifying business logic.

Provider adapters should remain isolated from the rest of the application.

Development environments should use development or restricted credentials whenever providers support them.

## 9. Testing Before Deployment

Changes should be validated before reaching production.

At minimum, the deployment process should verify:

* Automated tests pass.
* Database migrations can be applied.
* Required environment configuration is present.
* Critical external integrations are functioning.
* The application starts correctly.

The detailed testing strategy is defined separately.

## 10. CI/CD

Wanderes should use a simple CI/CD pipeline.

A typical workflow is:

```text id="c8yqj4"
Git Push
   ↓
Automated Tests
   ↓
Build / Validation
   ↓
Deploy
   ↓
Health Check
```

The initial pipeline should avoid unnecessary complexity.

Automated deployment can be introduced once the deployment environment is stable.

## 11. Database Migrations

Database schema changes must be managed through Django migrations.

Migrations should be:

* Committed to source control.
* Tested before deployment.
* Applied in a controlled deployment process.
* Designed to minimize risk to existing data.

Production database changes should never rely on manually modifying the schema.

## 12. Backups & Recovery

Production PostgreSQL data must be backed up regularly.

The backup strategy should include:

* Automated backups.
* Appropriate retention.
* Secure backup storage.
* Periodic recovery testing.

A backup that has never been successfully restored should not be considered a reliable recovery strategy.

Redis data generally does not represent the permanent source of truth and can usually be recreated from PostgreSQL or external systems.

## 13. Monitoring

Production should monitor the health of:

* Django.
* PostgreSQL.
* Redis.
* Background workers.
* AI providers.
* External travel providers.

Important signals include:

* Application errors.
* Response times.
* Database performance.
* Background job failures.
* Provider failures.
* Resource usage.

Critical failures should generate alerts.

## 14. Deployment Strategy

The initial deployment should favor a simple managed or hosted infrastructure rather than operating a large custom platform.

The system should be deployable as a small number of services:

```text id="w4x8ef"
Web / Django
     ↓
PostgreSQL
Redis
Background Worker
```

The exact hosting provider can be selected later based on cost, reliability, geographic requirements, and operational simplicity.

## 15. Operational Principle

> **Use the simplest infrastructure that reliably runs Wanderes, and add operational complexity only when scale or reliability requirements justify it.**
