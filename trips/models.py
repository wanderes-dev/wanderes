from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

# How a price compares to what's typical for this route/stay — distinct
# from the traveler-facing 1-10 `rating` scale below.
PRICE_RATE_CHOICES = [
    (1, _("Much cheaper than usual")),
    (2, _("Cheaper than usual")),
    (3, _("Typical price")),
    (4, _("More expensive than usual")),
    (5, _("Much more expensive than usual")),
]

TRIP_STATUS_CHOICES = [
    ("planned", _("Planned")),
    ("completed", _("Completed")),
    ("cancelled", _("Cancelled")),
]

# Initial feedback taxonomy, decided with the user 2026-08-29 (Phase 14,
# 15_IMPLEMENTATION_GUIDE.md: "Define the initial feedback taxonomy. Keep
# it small."). Deliberately not enforced as a DB choices= constraint since
# `Feedback.tags` is a JSONField list - FeedbackForm restricts the UI to
# these values instead.
FEEDBACK_TAG_CHOICES = [
    ("excellent_food", _("Excellent food")),
    ("great_value", _("Great value")),
    ("friendly_locals", _("Friendly locals")),
    ("beautiful_scenery", _("Beautiful scenery")),
    ("too_crowded", _("Too crowded")),
    ("overpriced", _("Overpriced")),
    ("poor_weather", _("Poor weather")),
    ("hard_to_get_around", _("Hard to get around")),
]


def rating_validators():
    return [MinValueValidator(1), MaxValueValidator(10)]


class Trip(models.Model):
    """A planned or completed travel experience belonging to a user.

    Trip Items beyond flights/accommodations (activities, reservations,
    etc.) are explicitly deferred to the dedicated Trip Management
    milestone — not needed for the first recommendation vertical slice.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="trips"
    )
    name = models.CharField(
        max_length=200,
        blank=True,
        verbose_name=_("name"),
        help_text=_("A short nickname, e.g. 'Summer in Lisbon'."),
    )
    destination = models.ForeignKey(
        "travel.Destination",
        on_delete=models.PROTECT,
        related_name="trips",
        verbose_name=_("destination"),
    )
    start_date = models.DateField(null=True, blank=True, verbose_name=_("start date"))
    end_date = models.DateField(null=True, blank=True, verbose_name=_("end date"))
    status = models.CharField(
        max_length=20, choices=TRIP_STATUS_CHOICES, default="planned", verbose_name=_("status")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name or f"{self.user.email} -> {self.destination.name} ({self.status})"


class TripFlight(models.Model):
    """One flight leg belonging to a trip.

    A trip with connecting flights or a round trip is represented as
    multiple TripFlight rows (ordered by leg_order), rather than nesting
    connection details inside a single record.
    """

    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="flights")
    flight_number = models.CharField(max_length=20)
    airline = models.CharField(max_length=200)
    departure_at = models.DateTimeField()
    duration = models.DurationField()
    leg_order = models.PositiveSmallIntegerField(
        default=1, help_text=_("Order of this leg within the trip's itinerary (1, 2, 3...).")
    )
    is_connecting = models.BooleanField(
        default=False,
        help_text=_("True if this leg is a connecting flight, not the first/only leg."),
    )
    price = models.DecimalField(max_digits=10, decimal_places=2)
    price_rate = models.PositiveSmallIntegerField(
        choices=PRICE_RATE_CHOICES,
        help_text=_("How this price compares to the historical price for this route."),
    )
    rating = models.PositiveSmallIntegerField(validators=rating_validators())

    class Meta:
        ordering = ["leg_order"]

    def __str__(self):
        return f"{self.flight_number} ({self.airline}) - leg {self.leg_order}"


class TripAccommodation(models.Model):
    """A lodging/hotel booking belonging to a trip."""

    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="accommodations")
    name = models.CharField(max_length=200, blank=True)
    address = models.CharField(max_length=500)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    price_rate = models.PositiveSmallIntegerField(
        choices=PRICE_RATE_CHOICES,
        help_text=_("How this price compares to the historical price for this stay."),
    )
    rating = models.PositiveSmallIntegerField(validators=rating_validators())
    link = models.URLField(blank=True)
    website = models.URLField(blank=True)

    def __str__(self):
        return self.name or self.address


class TravelHistoryEntry(models.Model):
    """A record that the user has actually visited a destination.

    Distinct from Trip (04_DATABASE_DESIGN.md §2 lists them as separate
    entities): a Trip is a planned/completed travel experience with its
    own items (flights, accommodations); this is a much simpler standalone
    record - "I've been to X, roughly around year Y" - usable even without
    ever creating a full Trip. Both feed the same repetition-penalty
    scoring in recommendations.scoring.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="travel_history"
    )
    destination = models.ForeignKey(
        "travel.Destination",
        on_delete=models.CASCADE,
        related_name="travel_history",
        verbose_name=_("destination"),
    )
    visited_year = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        verbose_name=_("visited year"),
        help_text=_("Approximate year of the visit, if known."),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-visited_year", "-created_at"]
        verbose_name_plural = _("travel history entries")

    def __str__(self):
        return f"{self.user.email} visited {self.destination.name}"


class Feedback(models.Model):
    """A user's evaluation of a destination or trip.

    Community-facing aggregation (CommunityReview, AggregatedInsight,
    TravelerSimilarityData) is explicitly out of scope here — deferred to
    the later Community Intelligence phases.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="feedback"
    )
    destination = models.ForeignKey(
        "travel.Destination",
        on_delete=models.CASCADE,
        related_name="feedback",
        null=True,
        blank=True,
    )
    trip = models.ForeignKey(
        Trip, on_delete=models.CASCADE, related_name="feedback", null=True, blank=True
    )
    rating = models.PositiveSmallIntegerField(
        validators=rating_validators(), verbose_name=_("rating")
    )
    tags = models.JSONField(
        default=list,
        blank=True,
        verbose_name=_("tags"),
        help_text=_("List of positive/negative tags."),
    )
    comment = models.TextField(blank=True, verbose_name=_("comment"))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(destination__isnull=False) | models.Q(trip__isnull=False),
                name="feedback_has_destination_or_trip",
            )
        ]

    def __str__(self):
        target = self.destination or self.trip
        return f"Feedback by {self.user.email} on {target}"
