from django.db import IntegrityError, transaction
from django.test import TestCase

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


class AffiliateLinkModelTests(TestCase):
    def setUp(self):
        self.destination = _make_destination()

    def test_can_create_a_link(self):
        link = AffiliateLink.objects.create(
            destination=self.destination,
            network="cj",
            advertiser_id="4347393",
            advertiser_name="Booking.com Spain and Portugal",
            link_id="11470088",
            link_name="Book Lisbon hotels",
            destination_url="https://www.booking.com/city/pt/lisbon.html",
            tracking_url="https://www.tkqlhce.com/click-3074780-11470088",
            targeted_countries=["Portugal", "Spain"],
        )

        self.assertEqual(link.destination, self.destination)
        self.assertIn("CJ Affiliate", str(link))

    def test_deleting_destination_cascades(self):
        AffiliateLink.objects.create(
            destination=self.destination,
            network="cj",
            advertiser_id="4347393",
            link_id="11470088",
            destination_url="https://www.booking.com/city/pt/lisbon.html",
            tracking_url="https://www.tkqlhce.com/click-3074780-11470088",
        )

        self.destination.delete()

        self.assertFalse(AffiliateLink.objects.exists())

    def test_same_network_and_link_id_cannot_repeat(self):
        AffiliateLink.objects.create(
            destination=self.destination,
            network="cj",
            advertiser_id="4347393",
            link_id="11470088",
            destination_url="https://www.booking.com/city/pt/lisbon.html",
            tracking_url="https://www.tkqlhce.com/click-3074780-11470088",
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            AffiliateLink.objects.create(
                destination=self.destination,
                network="cj",
                advertiser_id="4347393",
                link_id="11470088",
                destination_url="https://www.booking.com/city/pt/lisbon.html",
                tracking_url="https://www.tkqlhce.com/click-3074780-11470088",
            )
