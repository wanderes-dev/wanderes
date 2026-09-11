from django.conf import settings
from django.db import models

# Only events for features that actually exist in the app - premium_started
# and affiliate_link_clicked aren't here since there's no monetization or
# affiliate provider yet to instrument. Add them when those features ship,
# not speculatively.
#
# llm_request_completed/provider_request_completed are one event per
# completed attempt, not a started/completed/failed triple - a synchronous
# call always finishes 1:1 with its start, so "started" carries no signal.
# recommendation_viewed/recommendation_rejected were considered and left
# out too: no separate results page for the former, no reject/dismiss UI
# action for the latter, so "rejection" would be a derived metric, not a
# raw event (see documentation/16_ANALYTICS_ARCHITECTURE.md).
EVENT_TYPE_CHOICES = [
    ("user_registered", "User registered"),
    ("profile_completed", "Traveler profile completed"),
    ("travel_question_submitted", "Travel question submitted"),
    ("recommendation_generated", "Recommendation generated"),
    ("trip_created", "Trip created"),
    ("feedback_submitted", "Feedback submitted"),
    ("destination_selected", "Destination selected (Choose this trip)"),
    ("signup_started", "Signup started"),
    ("anonymous_user_authenticated", "Anonymous visitor authenticated"),
    ("llm_request_completed", "LLM request completed"),
    ("provider_request_completed", "External provider request completed"),
]

# System telemetry about the AI/provider layers, not user behavior - no
# actor (no user, no IP) by design. record_event() exempts these from the
# "must resolve user or IP" rule every other event type still enforces.
OPERATIONAL_EVENT_TYPES = {"llm_request_completed", "provider_request_completed"}


class Event(models.Model):
    """A single product-analytics event.

    Self-hosted and first-party - nothing goes to a third-party vendor.
    Deliberately minimal: only structured metadata is stored, never
    free-text message/comment content (that already lives on the relevant
    domain model, e.g. trips.Feedback.comment - duplicating it here would
    just be extra privacy exposure for no benefit).

    Every event belongs to exactly one of `user` (authenticated) or
    `anonymized_ip` (anonymous, e.g. an unauthenticated chat message) -
    never both. The IP is always anonymized before storage (see
    analytics.services), never the raw address. The two
    OPERATIONAL_EVENT_TYPES are the exception - neither field is set for
    those, by design.

    Enforced by analytics.services.record_event() at creation time, not by a
    DB CheckConstraint: `user` uses on_delete=SET_NULL so an authenticated
    event survives its user being deleted (keeps aggregate historical
    metrics instead of deleting the account holder's data twice over) - a
    "user or IP" constraint would turn that legitimate SET_NULL transition
    into an IntegrityError, blocking account deletion for anyone with
    analytics history. A row with both fields null after a user deletion is
    fine - it just drops out of user-scoped metrics.
    """

    event_type = models.CharField(max_length=40, choices=EVENT_TYPE_CHOICES)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="analytics_events",
        help_text="Set for authenticated events. Null for anonymous events.",
    )
    anonymized_ip = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text=(
            "Set only for anonymous events (last IPv4 octet / last 80 IPv6 bits "
            "zeroed before storage - see analytics.services._anonymize_ip)."
        ),
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Small structured payload (e.g. destination slug, rating). Never free text.",
    )
    conversation_key = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        db_index=True,
        help_text=(
            "The exact string ai.memory.conversation_key() produces for this "
            "event, when it happened inside a chat conversation - lets "
            "chat-related events be joined together. NOT itself a "
            "per-conversation identifier for an authenticated user (it's "
            "stable for that user's entire chat history, chat-history:user:"
            "{pk}) - the warehouse layer splits it into real conversation "
            "episodes via a 30-minute-inactivity session gap. Null for "
            "events with no conversation context (e.g. registration)."
        ),
    )
    locale = models.CharField(
        max_length=10,
        blank=True,
        help_text="request.LANGUAGE_CODE at the time of the event, when available.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["event_type", "created_at"]),
            models.Index(fields=["user", "created_at"]),
        ]

    def __str__(self):
        actor = self.user.email if self.user else f"anon {self.anonymized_ip}"
        return f"{self.event_type} by {actor} at {self.created_at:%Y-%m-%d %H:%M}"


class DailyProductMetrics(models.Model):
    """One row per calendar date, refreshed nightly by
    analytics.tasks.refresh_daily_metrics - the one real MATERIALIZED table
    in the warehouse (everything else in analytics/warehouse/ is a plain
    view, computed live). It's a table instead of a view because the
    dashboard hits this repeatedly and the underlying computation (scanning
    the full event history grouped by day) only gets slower as history
    grows - materializing at daily granularity keeps dashboard queries fast
    regardless of event volume.

    Full recompute-and-upsert each run rather than incremental counters,
    same idempotent/retry-safe pattern as
    trips.tasks.update_traveler_preferences_from_feedback - a retried
    refresh for the same date can't double-count.

    `computed_at` is the freshness signal: if MAX(computed_at) is more than
    ~26 hours old, the nightly job has stalled.
    """

    date = models.DateField(primary_key=True)
    conversations_started = models.PositiveIntegerField(default=0)
    unique_anonymous_conversations = models.PositiveIntegerField(default=0)
    messages_sent = models.PositiveIntegerField(default=0)
    conversations_reached_recommendation = models.PositiveIntegerField(default=0)
    recommendations_generated = models.PositiveIntegerField(default=0)
    destinations_recommended = models.PositiveIntegerField(default=0)
    destinations_selected = models.PositiveIntegerField(default=0)
    destinations_saved = models.PositiveIntegerField(default=0)
    signups_started = models.PositiveIntegerField(default=0)
    signups_completed = models.PositiveIntegerField(default=0)
    anonymous_visitors_authenticated = models.PositiveIntegerField(default=0)
    feedback_submitted = models.PositiveIntegerField(default=0)
    feedback_positive = models.PositiveIntegerField(default=0)
    ai_requests_total = models.PositiveIntegerField(default=0)
    ai_requests_failed = models.PositiveIntegerField(default=0)
    ai_latency_p50_ms = models.DecimalField(max_digits=10, decimal_places=1, null=True)
    ai_latency_p95_ms = models.DecimalField(max_digits=10, decimal_places=1, null=True)
    ai_latency_p99_ms = models.DecimalField(max_digits=10, decimal_places=1, null=True)
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date"]
        verbose_name_plural = "daily product metrics"


# Warehouse (dimension/fact) models live in analytics/warehouse/models.py.
# Imported at the bottom, not the top - Django's app loading only
# auto-imports <app>/models.py, never an arbitrary submodule, and nothing
# above this line depends on them anyway.
from .warehouse.models import (  # noqa: E402, F401
    DimDestination,
    DimUser,
    FactAiRequest,
    FactConversation,
    FactFeedback,
    FactRecommendation,
)
