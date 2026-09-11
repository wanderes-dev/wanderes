from django.db import models

# First model this app has needed - everything else here is stateless
# adapters (10_EXTERNAL_INTEGRATIONS.md §3), nothing to persist. An
# AffiliateLink is different: it's a real record of a link CJ's Link
# Search API actually returned (see affiliates/cj.py), worth keeping
# around. Lives here rather than in `travel` or `trips` since it's about
# the affiliate-network relationship, not traveler data or the
# destination catalog.

NETWORK_CHOICES = [
    ("cj", "CJ Affiliate"),
]


class AffiliateLink(models.Model):
    """A currently-known affiliate link fetched from a network - never
    fabricated. Every field here is a direct copy of what the network's
    API returned (see affiliates.cj.CJAffiliateProvider); nothing here is
    invented or guessed (05_AI_DESIGN.md §7 applies to this data too).

    Not wired into recommendations.scoring, the AI pipeline, or any
    template yet - see 10_EXTERNAL_INTEGRATIONS.md §13.8 and
    DECISIONS_PENDING.md §4. For now this just gives us a queryable
    record of what links actually exist, ahead of deciding how (or
    whether) to surface them.

    `fetched_at` is a freshness signal, not a guarantee - CJ links can be
    updated or deactivated by the advertiser at any time, and an inactive
    link just stops showing up in search results rather than being
    flagged. Re-fetch periodically instead of trusting an old row.
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
