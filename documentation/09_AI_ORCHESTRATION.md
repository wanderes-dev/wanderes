# 09 — AI Orchestration

## 1. Purpose

AI orchestration defines how Wanderes coordinates the AI model with application logic, traveler data, travel information, and external services.

The goal is to provide an intelligent conversational experience while keeping important business decisions under application control.

Wanderes should use a **controlled AI orchestration approach** rather than a fully autonomous AI agent.

## 2. Core Principle

The AI model should not control the entire application.

The responsibilities are divided:

```text id="j5c8ad"
Application
 ├── Authentication
 ├── Authorization
 ├── Data access
 ├── Business rules
 ├── Recommendation scoring
 └── External integrations

AI
 ├── Understand user intent
 ├── Reason about provided information
 ├── Compare options
 ├── Generate explanations
 └── Produce natural-language responses
```

This makes the system more predictable, secure, and easier to debug.

## 3. Request Lifecycle

A typical AI request follows this process:

```text id="tqj5o0"
User Message
     ↓
Request Validation
     ↓
Intent Understanding
     ↓
Authorized Context Construction
     ↓
Travel Data Retrieval
     ↓
Rules & Constraints
     ↓
Recommendation / Tool Processing
     ↓
AI Reasoning
     ↓
Response Validation
     ↓
Streaming Response
     ↓
User
```

Not every request requires every step.

For example, a simple destination question may require less processing than a personalized trip recommendation.

## 4. Context Construction

Before calling the AI model, Wanderes constructs a context containing only information relevant to the request.

Possible context sources include:

* Current user message.
* Conversation context.
* Traveler profile.
* Relevant travel history.
* Relevant preferences.
* Previous feedback.
* Retrieved destination information.
* Recommendation results.
* Current travel constraints.

The application decides which information can be included.

The AI model must not have unrestricted access to the database.

## 5. AI Tools & External Data

When the AI needs information that is not already available, the orchestration layer may invoke controlled tools.

Examples include:

* Destination search.
* Flight search.
* Hotel search.
* Weather or climate information.
* Maps and location data.
* Other approved travel services.

The AI may request a tool operation, but the application controls whether that operation is allowed and what data is returned.

Conceptually:

```text id="8g9k9s"
AI
 ↓
Requests Tool
 ↓
Application Validates Request
 ↓
Integration Executes
 ↓
Result Returned to AI
 ↓
AI Continues Reasoning
```

This prevents the AI from directly accessing external services or internal systems.

## 6. AI vs. Application Responsibilities

The application is responsible for deterministic decisions such as:

* User permissions.
* Subscription limits.
* Data access.
* Explicit constraints.
* Safety and platform restrictions.
* Recommendation scoring.
* External API access.

The AI is responsible for tasks such as:

* Understanding natural-language requests.
* Interpreting preferences.
* Comparing valid options.
* Explaining trade-offs.
* Asking useful clarification questions.
* Producing natural-language responses.

AI output should never override application-level permissions or deterministic constraints.

## 7. Conversation Memory

Conversation context should be handled separately from persistent traveler memory.

**Conversation context** contains information needed to understand the current interaction.

**Traveler memory** contains information intentionally retained because it may improve future experiences.

For example:

```text id="wl5g9a"
Conversation Context
"I don't want to visit Spain again on this trip."

Traveler Memory
"User has previously visited Spain."
```

Not every statement in a conversation should become persistent memory.

The application should determine when information is important enough to store.

## 8. Streaming

AI responses should be streamed when appropriate.

Instead of waiting for the complete response:

```text id="z8rj6m"
Request
  ↓
AI generates response
  ↓
Complete response
  ↓
Browser
```

Wanderes should support:

```text id="ypxv2p"
Request
  ↓
AI generates response
  ↓
Partial response
  ↓
Browser
  ↓
More response
  ↓
Browser
  ↓
Complete
```

This improves perceived performance and makes the conversation feel more natural.

Streaming should not bypass response validation or application-level controls.

## 9. Response Validation

AI output should be validated before being treated as trusted application data.

The system should detect issues such as:

* Invalid structured output.
* Unsupported tool results.
* Missing required information.
* Contradictions with deterministic constraints.
* Unexpected content outside Wanderes's scope.

Where structured AI output is required, the application should validate it against an explicit schema.

Natural-language responses can then be generated from validated application data.

## 10. Travel Scope

Wanderes is intentionally limited to travel-related assistance.

The orchestration layer should detect requests that fall outside the product's intended scope and respond appropriately.

The AI should not become a general-purpose assistant simply because the underlying model is capable of answering unrelated questions.

## 11. AI Provider Abstraction

The application should communicate with an internal AI interface rather than directly coupling business logic to one provider.

Conceptually:

```text id="k3x4wq"
Wanderes
     ↓
AI Interface
     ↓
AI Provider
```

The abstraction should allow the provider or model to change without requiring major changes to the recommendation system.

Provider-specific functionality should remain isolated.

## 12. Failure Handling

AI and external services can fail.

The system should handle:

* Provider timeouts.
* Rate limits.
* Temporary provider failures.
* Invalid model responses.
* Tool failures.
* Missing travel data.
* Partial or incomplete results.

Failures should produce useful user-facing responses without exposing internal implementation details.

Where possible, the application should retry transient failures safely.

## 13. Cost & Token Management

AI usage should be controlled because model calls are potentially expensive.

The system should:

* Send only relevant context.
* Avoid unnecessarily large conversation histories.
* Reuse cached information where appropriate.
* Select models according to task complexity.
* Avoid repeated calls when existing results are sufficient.
* Monitor AI usage and costs.

The initial implementation should optimize based on observed usage rather than introducing a complex model-routing system immediately.

## 14. Initial Architecture

The first version should use a controlled orchestration pipeline:

```text id="w5x3c9"
Django Request
      ↓
AI Orchestrator
      ↓
Context + Tools + Rules
      ↓
AI Provider
      ↓
Validated Result
      ↓
Streaming Response
```

Wanderes should not initially implement autonomous planning loops, unrestricted tool access, or complex multi-agent systems.

Additional AI complexity should only be introduced when a demonstrated product requirement justifies it.

## 15. Principle

> **Use AI for reasoning and communication, but keep control of data, permissions, rules, and business decisions inside the application.**
