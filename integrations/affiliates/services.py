from . import get_affiliate_network_provider
from .base import AffiliateNetworkError


def fetch_and_save_link_for_destination(destination, *, provider=None):
    """Search for a real affiliate link for one Destination and persist it
    as an AffiliateLink - connects the provider interface in
    integrations.affiliates to integrations.models.AffiliateLink.

    Searches by the destination's country (the same reliable,
    English-canonical join key travel.services.get_entry_requirements()
    uses). Takes the first result CJ's own relevance ranking returns -
    never fabricates one, and returns None (not a placeholder row) if the
    network has nothing for this destination.

    Upserts by (network, destination, link_id), so re-running this for
    the same destination refreshes fetched_at and any changed fields
    instead of piling up duplicate rows for the same link.

    Lets AffiliateNetworkError propagate rather than swallowing it -
    unlike analytics.services.record_event this isn't fire-and-forget; a
    caller needs to know a fetch actually failed.
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
