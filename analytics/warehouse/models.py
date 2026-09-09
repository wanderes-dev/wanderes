"""Django models mapped onto the read-only Postgres views defined in
analytics/warehouse/sql/ (2026-09-09, analytics/data-engineering pass).

Every model here is `managed = False` - Django never creates, alters, or
drops these tables via migrate; the one migration in this app
(0003_create_warehouse_views.py) creates the underlying VIEWs directly via
RunSQL, reading the same .sql files these models document. Mapping them
as real Django models (rather than only raw SQL) gives a typed,
discoverable, testable Python interface on top of the same views a `psql`
session or a future BI tool could query directly - both paths see exactly
the same data, since a view has no state of its own beyond its query.

See each .sql file's own header comment for that model's grain, primary
key, source, business meaning, and update frequency - not repeated here to
avoid the two documentation sources drifting apart.
"""

from django.db import models


class DimDestination(models.Model):
    destination_id = models.BigIntegerField(primary_key=True)
    slug = models.CharField(max_length=50)
    name = models.CharField(max_length=200)
    country = models.CharField(max_length=200)
    trip_type = models.CharField(max_length=20)
    cost_of_living = models.SmallIntegerField()
    has_video = models.BooleanField()
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "dim_destinations"


class DimUser(models.Model):
    user_id = models.BigIntegerField(primary_key=True)
    date_joined = models.DateTimeField()
    last_login = models.DateTimeField(null=True)
    preferred_language = models.CharField(max_length=10)
    is_staff = models.BooleanField()
    home_country = models.CharField(max_length=200, null=True)
    preferred_cost_of_living = models.SmallIntegerField(null=True)
    has_traveler_profile = models.BooleanField()

    class Meta:
        managed = False
        db_table = "dim_users"


class FactConversation(models.Model):
    id = models.CharField(max_length=32, primary_key=True)
    conversation_key = models.CharField(max_length=255)
    episode_number = models.IntegerField()
    started_at = models.DateTimeField()
    last_event_at = models.DateTimeField()
    user_id = models.BigIntegerField(null=True)
    locale = models.CharField(max_length=10, null=True)
    message_count = models.IntegerField()
    reached_recommendation = models.BooleanField()
    reached_selection = models.BooleanField()
    reached_trip_created = models.BooleanField()
    reached_feedback = models.BooleanField()

    class Meta:
        managed = False
        db_table = "fact_conversations"


class FactRecommendation(models.Model):
    id = models.CharField(max_length=32, primary_key=True)
    conversation_key = models.CharField(max_length=255)
    episode_number = models.IntegerField()
    destination_slug = models.CharField(max_length=50)
    recommended_at = models.DateTimeField()
    was_selected = models.BooleanField()
    was_saved = models.BooleanField()

    class Meta:
        managed = False
        db_table = "fact_recommendations"


class FactAiRequest(models.Model):
    event_id = models.BigIntegerField(primary_key=True)
    event_type = models.CharField(max_length=40)
    operation = models.CharField(max_length=100, null=True)
    success = models.BooleanField(null=True)
    latency_ms = models.DecimalField(max_digits=12, decimal_places=1, null=True)
    error_type = models.CharField(max_length=100, null=True)
    conversation_key = models.CharField(max_length=255, null=True)
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "fact_ai_requests"


class FactFeedback(models.Model):
    feedback_id = models.BigIntegerField(primary_key=True)
    user_id = models.BigIntegerField()
    destination_id = models.BigIntegerField(null=True)
    destination_slug = models.CharField(max_length=50, null=True)
    rating = models.SmallIntegerField()
    tags = models.JSONField()
    trip_id = models.BigIntegerField(null=True)
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "fact_feedback"
