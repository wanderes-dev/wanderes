from django.conf import settings
from django.db import models

# Phase 17 (Product Analytics) event taxonomy, decided with the user
# 2026-08-30: only events for features that already exist. premium_started
# and affiliate_link_clicked from the guide's candidate list are deliberately
# NOT included yet - those features (monetization, affiliate provider) don't
# exist in the app, so there is nothing real to instrument. Add them when
# those features are actually built, not speculatively now.
EVENT_TYPE_CHOICES = [
    ("user_registered", "User registered"),
    ("profile_completed", "Traveler profile completed"),
    ("travel_question_submitted", "Travel question submitted"),
    ("recommendation_generated", "Recommendation generated"),
    ("trip_created", "Trip created"),
    ("feedback_submitted", "Feedback submitted"),
]


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
    the raw address.

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
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["event_type", "created_at"]),
            models.Index(fields=["user", "created_at"]),
        ]

    def __str__(self):
        actor = self.user.email if self.user else f"anon {self.anonymized_ip}"
        return f"{self.event_type} by {actor} at {self.created_at:%Y-%m-%d %H:%M}"
