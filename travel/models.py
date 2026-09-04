from django.db import models
from django.utils.translation import gettext_lazy as _

# Canonical source for both choice lists (2026-09-02 - previously
# duplicated byte-for-byte in users.models, and a third time as a
# hardcoded enum in ai.orchestration's INTENT_SCHEMA/prompt, with nothing
# keeping the three in sync). travel owns the destination catalog these
# describe, so it's the natural single source of truth - users.models
# imports and re-exports COST_OF_LIVING_CHOICES from here, and
# ai.orchestration derives its intent-extraction schema's trip_type enum
# from TRIP_TYPE_CHOICES directly instead of hardcoding its own copy.
#
# Only the labels are wrapped in gettext_lazy, never the stored codes
# (1-5, "beach"/"city"/etc.) - ai.orchestration.TRIP_TYPE_CODES extracts
# just the code half of each tuple, so translating the label can never
# affect the AI's own intent-extraction schema or any stored DB value.
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


class CountryEntryRequirement(models.Model):
    """Visa/vaccine/insurance entry guidance for one destination country
    (2026-09-02, direct user request - "tabela de country regulation").

    IMPORTANT - a fundamentally higher-stakes category of data than
    Destination's descriptive travel facts: a traveler relying on a wrong
    visa or vaccine requirement can be denied boarding, denied entry, or
    face a real legal/health problem (some countries legally require proof
    of a specific vaccination at the border). This data is compiled from
    general knowledge, not verified against each country's official
    government/embassy source, and does NOT cover every UN member state -
    see travel/data/country_entry_requirements.json's own $schema_note for
    the honest coverage/confidence account. For this reason:

    - `travel.services.ENTRY_REQUIREMENT_DISCLAIMER` MUST be shown
      alongside this data wherever it is ever displayed or referenced -
      never presented as a substitute for an official source. This is
      enforced by convention (there is no automatic way to guarantee a
      future caller includes it), so any new code path that surfaces this
      data must carry the disclaimer explicitly, the same way
      05_AI_DESIGN.md §7 already requires for any AI-generated content.
    - Visa requirements genuinely depend on the traveler's own
      nationality, not just the destination - `visa_required_nationalities`
      is deliberately a list (which nationalities need a visa for this
      destination), not a single yes/no flag, so that nationality
      dependency is structurally represented rather than flattened away.
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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["country"]
        verbose_name = "country entry requirement"
        verbose_name_plural = "country entry requirements"

    def __str__(self):
        return f"Entry requirements for {self.country}"
