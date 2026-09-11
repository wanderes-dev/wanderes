from django.db import models
from django.utils.translation import gettext_lazy as _

# Canonical source for both choice lists - used to be duplicated in
# users.models and again as a hardcoded enum in ai.orchestration's
# INTENT_SCHEMA. travel owns the destination catalog these describe, so
# it's the natural home for them: users.models re-exports
# COST_OF_LIVING_CHOICES from here, and ai.orchestration derives its
# trip_type enum from TRIP_TYPE_CHOICES instead of keeping its own copy.
#
# Only the labels are gettext_lazy, never the stored codes (1-5,
# "beach"/"city"/...) - TRIP_TYPE_CODES in ai.orchestration pulls just
# the code half of each tuple, so translating a label can't affect
# intent extraction or anything stored in the DB.
COST_OF_LIVING_CHOICES = [
    (1, _("Very low")),
    (2, _("Low")),
    (3, _("Medium")),
    (4, _("High")),
    (5, _("Very high")),
]

TRIP_TYPE_CHOICES = [
    ("beach", _("Beach")),
    ("city", _("City")),
    ("nature", _("Nature")),
    ("culture", _("Culture")),
]


class Destination(models.Model):
    """A place that can be recommended, visited, planned, or discussed.

    Shaped to match travel/data/curated_destinations.json so loading it
    is a straight import rather than a redesign. Climate data isn't
    stored here on purpose - it's fetched live from Open-Meteo by
    coordinates at request time, keeping static facts separate from
    live weather.
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


class CountryEntryRequirement(models.Model):
    """Visa/vaccine/insurance entry guidance for one destination country.

    Higher stakes than Destination's descriptive travel facts: a wrong
    visa or vaccine requirement can get a traveler denied boarding or
    entry, or into a real legal/health problem. This data is compiled
    from general knowledge, not verified against each country's official
    government/embassy source, and doesn't cover every UN member state -
    see travel/data/country_entry_requirements.json's own $schema_note
    for the honest coverage picture. Because of that:

    - `travel.services.ENTRY_REQUIREMENT_DISCLAIMER` must be shown
      alongside this data wherever it's displayed or referenced, never
      as a substitute for an official source. Nothing enforces this
      automatically, so any new code path surfacing this data has to add
      the disclaimer itself.
    - Visa requirements depend on the traveler's own nationality, not
      just the destination, so `visa_required_nationalities` is a list
      (which nationalities need a visa here) rather than a single
      yes/no flag.
    """

    country = models.CharField(
        max_length=200,
        unique=True,
        help_text="The destination country these requirements apply to.",
    )
    visa_required_nationalities = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Nationalities that generally need a visa for a typical short "
            "tourist stay in this country, e.g. ['Brazil', 'Argentina']. "
            "Not exhaustive - see visa_notes for waiver programs/nuance."
        ),
    )
    visa_notes = models.TextField(
        blank=True,
        help_text=(
            "Free-form nuance - visa-waiver program names, e-visa availability, "
            "typical stay length allowed."
        ),
    )
    vaccine_requirements = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Vaccines required or recommended for entry, e.g. "
            "['Yellow Fever - required if arriving from an endemic country']."
        ),
    )
    insurance_required = models.BooleanField(
        default=False,
        help_text=(
            "Whether travel/health insurance is a formal entry requirement, "
            "not just a recommendation."
        ),
    )
    insurance_notes = models.TextField(blank=True)
    other_requirements = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Other entry requirements, e.g. "
            "['Minimum 6 months passport validity', 'Proof of onward travel']."
        ),
    )
    videos = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Travel videos for this country, as [url, language_code] pairs, "
            "e.g. [['https://www.youtube.com/watch?v=...', 'EN']]. "
            "language_code is whatever language the video itself is "
            "actually in, not necessarily one of the site's own supported "
            "UI languages. Sourced from web search (2026-09-07), not an "
            "official tourism catalog - same 'general knowledge, not "
            "verified' caveat already applied to the rest of this model."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["country"]
        verbose_name = "country entry requirement"
        verbose_name_plural = "country entry requirements"

    def __str__(self):
        return f"Entry requirements for {self.country}"
