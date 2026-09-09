from django.db import models

# The `integrations` app has never had a model before (2026-09-09) - it
# was deliberately pure Python + adapters (10_EXTERNAL_INTEGRATIONS.md
# §3's "External provider adapters live behind an internal interface" -
# stateless by design, nothing to persist). AffiliateLink is different in
# kind: a real, persisted record of a link CJ's Link Search API actually
# returned (integrations/affiliates/cj.py) - genuine business data worth
# keeping around (which links exist, when Wanderes last confirmed them),
# not a stateless adapter call. It lives here rather than in `travel` or
# `trips` because it's fundamentally about the external affiliate-network
# relationship, not the traveler's own data or the destination catalog
# itself.

NETWORK_CHOICES = [
    ("cj", "CJ Affiliate"),
]


class AffiliateLink(models.Model):
    """A real, currently-known affiliate link fetched from an affiliate
    network (2026-09-09) - never fabricated. Every field here is a direct
    copy of what the network's own API returned (see
    integrations.affiliates.cj.CJAffiliateProvider), never invented or
    guessed (05_AI_DESIGN.md §7's "never invent travel data" applies to
    this data just as much as to AI-facing content).

    Deliberately NOT wired into recommendations.scoring, the AI
    orchestration pipeline, or any traveler-facing template yet - see
    10_EXTERNAL_INTEGRATIONS.md §13.8 and DECISIONS_PENDING.md §4. This
    model exists to give Wanderes a real, queryable record of what links
    are actually available, in advance of a product decision about how
    (or whether) to surface them - "receive a source, not consume one
    yet," the same staged approach already used for the Kayak/Booking.com
    provider scaffolding.

    `fetched_at` is a freshness signal, not a guarantee - CJ links can be
    updated or deactivated by the advertiser at any time (per CJ's own
    docs, an inactive/archived link simply stops appearing in future
    search results, it isn't flagged inline) - re-fetch periodically
    rather than trusting an old row indefinitely.
    """

    destination = models.ForeignKey(
        "travel.Destination",
        on_delete=models.CASCADE,
        related_name="affiliate_links",
        help_text="The Wanderes destination this link was searched for.",
    )
    network = models.CharField(max_length=20, choices=NETWORK_CHOICES)
    advertiser_id = models.CharField(
        max_length=50, help_text="The network's own advertiser/merchant id (e.g. a CJ CID)."
    )
    advertiser_name = models.CharField(max_length=200, blank=True)
    link_id = models.CharField(max_length=50, help_text="The network's own id for this link.")
    link_name = models.CharField(max_length=255, blank=True)
    destination_url = models.URLField(
        max_length=1000, help_text="The advertiser's own destination URL, before tracking."
    )
    tracking_url = models.URLField(
        max_length=1000,
        help_text="The real, trackable link to actually send a traveler to.",
    )
    targeted_countries = models.JSONField(
        default=list,
        blank=True,
        help_text="Country names/codes the advertiser targeted this link for.",
    )
    fetched_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["network", "link_id"], name="unique_affiliate_link_per_network"
            )
        ]
        ordering = ["-fetched_at"]

    def __str__(self):
        return f"{self.get_network_display()} link for {self.destination.name}: {self.link_name}"
