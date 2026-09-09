from django.contrib import admin

from .models import AffiliateLink


@admin.register(AffiliateLink)
class AffiliateLinkAdmin(admin.ModelAdmin):
    list_display = ("destination", "network", "advertiser_name", "link_name", "fetched_at")
    list_filter = ("network",)
    search_fields = ("destination__name", "advertiser_name", "link_name")
    readonly_fields = (
        "network",
        "advertiser_id",
        "advertiser_name",
        "link_id",
        "link_name",
        "destination_url",
        "tracking_url",
        "targeted_countries",
        "fetched_at",
        "created_at",
    )
