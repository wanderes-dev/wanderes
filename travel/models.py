from django.db import models

# Same 1-5 scale used by users.TravelerProfile.preferred_cost_of_living.
COST_OF_LIVING_CHOICES = [
    (1, "Very low"),
    (2, "Low"),
    (3, "Medium"),
    (4, "High"),
    (5, "Very high"),
]

TRIP_TYPE_CHOICES = [
    ("beach", "Beach"),
    ("city", "City"),
    ("nature", "Nature"),
    ("culture", "Culture"),
]


class Destination(models.Model):
    """A place that can be recommended, visited, planned, or discussed.

    Shaped to match travel/data/curated_destinations.json (the
    approved Phase 3 seed dataset) so loading it is a straight import, not
    a redesign. Real-time climate data is intentionally NOT stored here —
    it's fetched live from Open-Meteo by coordinates at request time, per
    the Phase 3 decision to keep static facts and live weather separate.
    """

    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=200)
    country = models.CharField(max_length=200)
    latitude = models.DecimalField(max_digits=8, decimal_places=5)
    longitude = models.DecimalField(max_digits=8, decimal_places=5)
    trip_type = models.CharField(max_length=20, choices=TRIP_TYPE_CHOICES)
    cost_of_living = models.PositiveSmallIntegerField(choices=COST_OF_LIVING_CHOICES)
    best_season = models.CharField(max_length=200)
    worst_season = models.CharField(max_length=200)
    short_description = models.TextField()
    points_of_interest = models.JSONField(
        default=list, help_text="List of point-of-interest names, e.g. ['Tower of Belem']."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name}, {self.country}"
