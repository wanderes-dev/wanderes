from django.conf import settings
from django.db import models

# Phase 17 (Product Analytics) event taxonomy, decided with the user
# 2026-08-30: only events for features that already exist. premium_started
# and affiliate_link_clicked from the guide's candidate list are deliberately
# NOT included yet - those features (monetization, affiliate provider) don't
# exist in the app, so there is nothing real to instrument. Add them when
# those features are actually built, not speculatively now.
#
# Extended 2026-09-09 (analytics/data-engineering pass) with 5 more event
# types, same "only for features that already exist" discipline:
# destination_selected ("Choose this trip", shipped 2026-09-08, previously
# uninstrumented), signup_started (pairs with user_registered for a real
# signup funnel), anonymous_user_authenticated (an anonymous chat visitor
# logging into an existing account - distinct from user_registered, which
# only fires on registration), and two AI/provider operational events -
# llm_request_completed / provider_request_completed - deliberately ONE
# event per completed attempt rather than the started/completed/failed
# triple a naive taxonomy might use: a synchronous call always either
# completes or fails 1:1 with its start, so a "started" event carries no
# independent analytical value. recommendation_viewed and
# recommendation_rejected were considered and deliberately NOT added -
# see documentation/16_ANALYTICS_ARCHITECTURE.md for why (no separate
# results page for the former; no reject/dismiss UI action exists for the
# latter, so "rejection" is a derived metric, not a raw event).
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

# Operational/system telemetry about the AI and provider layers, not user
# behavior - these deliberately have no actor (no user, no IP). Exempted in
# record_event() from the "must resolve user or IP" requirement that every
# other event type still enforces unchanged (see record_event's docstring).
OPERATIONAL_EVENT_TYPES = {"llm_request_completed", "provider_request_completed"}


class Event(models.Model):
    """A single product-analytics event.

    Self-hosted, first-party analytics (Phase 17 decision) - no third-party
    analytics vendor, no data leaves this database. Deliberately minimal:
    only structured metadata is ever stored, never free-text message or
    comment content (that already lives on the relevant domain model, e.g.
    trips.Feedback.comment, for its own product reason - analytics has no
    need to duplicate it and duplicating it would only add privacy exposure
    for no product benefit).

    Every event is attributed to exactly one of `user` (an authenticated
    user) or `anonymized_ip` (an anonymous visitor, e.g. an unauthenticated
    chat message) - never both, per the Phase 17 decision that anonymous
    events are tracked by IP rather than a session identifier. The IP is
    always anonymized before being stored (see analytics.services), never
    the raw address. The two OPERATIONAL_EVENT_TYPES are the one exception -
    they have neither `user` nor `anonymized_ip` by design (see their own
    definition above).

    This is enforced by analytics.services.record_event() at creation time,
    deliberately NOT by a DB CheckConstraint: `user` uses on_delete=SET_NULL
    so an authenticated event survives its user's account being deleted
    (preserving aggregate historical metrics rather than deleting the
    account holder's data twice over) - a "user or IP" constraint would make
    that exact, legitimate SET_NULL transition raise an IntegrityError,
    effectively blocking account deletion for any user with analytics
    history. A row with both fields null after a user deletion is an
    accepted, harmless outcome (it just drops out of user-scoped metrics),
    not a data integrity problem worth blocking deletion over.
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
    analytics.tasks.refresh_daily_metrics (2026-09-09) - the one genuinely
    MATERIALIZED table in the warehouse (everything in
    analytics/warehouse/ is a plain view, recomputed live). A real table
    here, not a view, because the dashboard queries this repeatedly and
    its computation (scanning the full event history grouped by day) gets
    slower as that history grows - materializing at daily granularity
    keeps dashboard queries fast regardless of raw event volume.

    Full recompute-and-upsert each run, not incremental counters - same
    "recompute from scratch = idempotent and retry-safe" pattern already
    proven by trips.tasks.update_traveler_preferences_from_feedback, so a
    retried or re-run refresh for the same date can never double-count.

    `computed_at` is the freshness signal: if MAX(computed_at) is more
    than ~26 hours old, the nightly job has stalled - a realistic,
    checkable definition, not a fabricated SLA.
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


# Warehouse (dimension/fact) models live in analytics/warehouse/models.py,
# not here (2026-09-09) - imported at the bottom of this file, not the
# top, since it's what Django's app loading actually auto-imports
# (<app>/models.py only, never an arbitrary submodule on its own) and
# nothing above depends on them.
from .warehouse.models import (  # noqa: E402, F401
    DimDestination,
    DimUser,
    FactAiRequest,
    FactConversation,
    FactFeedback,
    FactRecommendation,
)
