import xml.etree.ElementTree as ET

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .base import AffiliateLinkResult, AffiliateNetworkError, AffiliateNetworkProvider

# CJ Developer Portal, Link Search API reference
# (developers.cj.com/docs/rest-apis/link-search) - read directly, not
# guessed at, same discipline as integrations/flights/kayak.py.
LINK_SEARCH_URL = "https://link-search.api.cj.com/v2/link-search"
REQUEST_TIMEOUT_SECONDS = 10
# Documented limit: 25 calls/minute, publishers only. Nothing here loops
# over it yet - noted for whoever adds bulk fetching later.
RATE_LIMIT_CALLS_PER_MINUTE = 25


class CJAffiliateProvider(AffiliateNetworkProvider):
    """CJ Affiliate's Link Search API - CJ's own link/product discovery
    API, authenticated with a personal access token (settings.CJ_API_TOKEN)
    plus a registered Website ID/PID (settings.CJ_WEBSITE_ID). Not
    Booking.com's Demand API - see this package's base.py docstring and
    10_EXTERNAL_INTEGRATIONS.md §13.8 for why that distinction matters.

    Parsing note: CJ's documented sample response shows an apparent
    double-nested <link><link>...</link>...</link> structure, which looks
    like a docs rendering artifact - the accompanying field table
    describes one flat set of fields per link, no second nesting level.
    We parse defensively (look for any <link> with a direct <link-id>
    child, not a fixed depth) so an extra wrapping level either way
    doesn't break it. Untested against a real live response (no
    CJ_WEBSITE_ID available while building this) - verify against one
    real response before trusting it for anything user-facing.
    """

    def search_links(
        self,
        *,
        advertiser_ids: list[str] | None = None,
        keywords: str | None = None,
        targeted_country: str | None = None,
    ) -> list[AffiliateLinkResult]:
        if not settings.CJ_API_TOKEN:
            raise ImproperlyConfigured(
                "CJ_API_TOKEN is not set. Add it to your .env file (see .env.example)."
            )
        if not settings.CJ_WEBSITE_ID:
            raise ImproperlyConfigured(
                "CJ_WEBSITE_ID is not set. Add it to your .env file (see .env.example) - "
                "this is your CJ Website ID/PID, a separate credential from CJ_API_TOKEN."
            )
        if not (advertiser_ids or keywords or targeted_country):
            raise ValueError(
                "search_links() needs at least one of advertiser_ids/keywords/"
                "targeted_country - CJ's own API returns zero results for an "
                "unfiltered request rather than 'everything'."
            )

        params = {"website-id": settings.CJ_WEBSITE_ID}
        if advertiser_ids:
            params["advertiser-ids"] = ",".join(advertiser_ids)
        if keywords:
            params["keywords"] = keywords
        if targeted_country:
            params["targeted-country"] = targeted_country

        try:
            response = requests.get(
                LINK_SEARCH_URL,
                params=params,
                headers={"Authorization": f"Bearer {settings.CJ_API_TOKEN}"},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise AffiliateNetworkError("Unable to reach CJ's Link Search API.") from exc

        try:
            return self._parse(response.text)
        except ET.ParseError as exc:
            raise AffiliateNetworkError("Unexpected response from CJ's Link Search API.") from exc

    @staticmethod
    def _parse(xml_text: str) -> list[AffiliateLinkResult]:
        root = ET.fromstring(xml_text)
        results = []
        for link_el in root.iter("link"):
            link_id = link_el.findtext("link-id")
            if link_id is None:
                # Skip non-record elements - e.g. an outer wrapping <link>
                # if that extra nesting level turns out to be real, not a
                # docs artifact. Only elements with their own link-id
                # count as records.
                continue

            raw_countries = link_el.findtext("targeted-countries") or ""
            targeted_countries = (
                [c.strip() for c in raw_countries.split(",") if c.strip()]
                if raw_countries and raw_countries.lower() != "null"
                else []
            )

            results.append(
                AffiliateLinkResult(
                    network="cj",
                    link_id=link_id,
                    advertiser_id=link_el.findtext("advertiser-id") or "",
                    advertiser_name=link_el.findtext("advertiser-name") or "",
                    link_name=link_el.findtext("link-name") or "",
                    destination_url=link_el.findtext("destination") or "",
                    tracking_url=link_el.findtext("clickUrl") or "",
                    targeted_countries=targeted_countries,
                )
            )
        return results
