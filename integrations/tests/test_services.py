from django.test import TestCase

from integrations.affiliates.base import AffiliateLinkResult
from integrations.affiliates.services import fetch_and_save_link_for_destination
from integrations.models import AffiliateLink
from travel.models import Destination


def _make_destination(slug="lisbon-pt", **overrides):
    defaults = {
        "name": "Lisbon",
        "country": "Portugal",
        "latitude": "38.72000",
        "longitude": "-9.14000",
        "trip_type": "city",
        "cost_of_living": 3,
        "best_season": "Mar-Oct",
        "worst_season": "Dec-Feb",
        "short_description": "A hilly coastal capital.",
        "points_of_interest": [],
    }
    defaults.update(overrides)
    return Destination.objects.create(slug=slug, **defaults)


class StubAffiliateProvider:
    def __init__(self, results):
        self.results = results
        self.search_calls = []

    def search_links(self, *, advertiser_ids=None, keywords=None, targeted_country=None):
        self.search_calls.append({"keywords": keywords})
        return self.results


class FetchAndSaveLinkForDestinationTests(TestCase):
    def setUp(self):
        self.destination = _make_destination()

    def test_saves_the_first_real_result(self):
        provider = StubAffiliateProvider(
            [
                AffiliateLinkResult(
                    network="cj",
                    link_id="11470088",
                    advertiser_id="4347393",
                    advertiser_name="Booking.com Spain and Portugal",
                    link_name="Book Lisbon hotels",
                    destination_url="https://www.booking.com/city/pt/lisbon.html",
                    tracking_url="https://www.tkqlhce.com/click-3074780-11470088",
                    targeted_countries=["Portugal"],
                )
            ]
        )

        link = fetch_and_save_link_for_destination(self.destination, provider=provider)

        self.assertIsNotNone(link)
        self.assertEqual(link.destination, self.destination)
        self.assertEqual(link.link_id, "11470088")
        self.assertEqual(provider.search_calls, [{"keywords": "Portugal"}])

    def test_no_results_returns_none_not_a_fabricated_link(self):
        provider = StubAffiliateProvider([])

        link = fetch_and_save_link_for_destination(self.destination, provider=provider)

        self.assertIsNone(link)
        self.assertFalse(AffiliateLink.objects.exists())

    def test_calling_again_updates_the_same_row_not_a_duplicate(self):
        result = AffiliateLinkResult(
            network="cj",
            link_id="11470088",
            advertiser_id="4347393",
            advertiser_name="Booking.com Spain and Portugal",
            link_name="Book Lisbon hotels",
            destination_url="https://www.booking.com/city/pt/lisbon.html",
            tracking_url="https://www.tkqlhce.com/click-3074780-11470088",
            targeted_countries=["Portugal"],
        )
        provider = StubAffiliateProvider([result])

        fetch_and_save_link_for_destination(self.destination, provider=provider)
        fetch_and_save_link_for_destination(self.destination, provider=provider)

        self.assertEqual(AffiliateLink.objects.count(), 1)

    def test_searches_by_destination_country(self):
        destination = _make_destination(slug="bali-id", name="Bali", country="Indonesia")
        provider = StubAffiliateProvider([])

        fetch_and_save_link_for_destination(destination, provider=provider)

        self.assertEqual(provider.search_calls, [{"keywords": "Indonesia"}])
