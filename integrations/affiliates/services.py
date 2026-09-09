from . import get_affiliate_network_provider
from .base import AffiliateNetworkError


def fetch_and_save_link_for_destination(destination, *, provider=None):
    """Search for a real affiliate link for one Destination and persist
    it as an AffiliateLink (2026-09-09) - the "generates" step connecting
    integrations.affiliates' provider interface to integrations.models
    .AffiliateLink.

    Searches by the destination's country (the same field every other
    part of this app already treats as the reliable, English-canonical
    join key - travel.services.get_entry_requirements() does the same).
    Takes the first real result CJ's own relevance ranking returns -
    never fabricates a link, and returns None (not a placeholder row) if
    the network genuinely has nothing for this destination.

    Upserts by (network, destination, link_id) so re-running this for the
    same destination refreshes fetched_at and any changed fields rather
    than accumulating duplicate rows for the same real link.

    Propagates AffiliateNetworkError on a network failure rather than
    swallowing it - unlike analytics.services.record_event, this isn't a
    fire-and-forget side channel; a caller (a future management command
    or admin action) needs to know a fetch genuinely failed rather than
    silently doing nothing.
    """
    from .. import models

    affiliate_provider = provider or get_affiliate_network_provider()
    results = affiliate_provider.search_links(keywords=destination.country)
    if not results:
        return None

    result = results[0]
    link, _created = models.AffiliateLink.objects.update_or_create(
        network=result.network,
        link_id=result.link_id,
        defaults={
            "destination": destination,
            "advertiser_id": result.advertiser_id,
            "advertiser_name": result.advertiser_name,
            "link_name": result.link_name,
            "destination_url": result.destination_url,
            "tracking_url": result.tracking_url,
            "targeted_countries": result.targeted_countries,
        },
    )
    return link


__all__ = ["fetch_and_save_link_for_destination", "AffiliateNetworkError"]
