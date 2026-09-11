from unittest.mock import Mock, patch

import requests
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings

from integrations.affiliates import get_affiliate_network_provider
from integrations.affiliates.base import AffiliateNetworkError
from integrations.affiliates.cj import CJAffiliateProvider

# Flat, single-nesting-level sample - matches the "Per Record (Link)"
# field table in CJ's docs, the more reliable source of truth than the
# page's own sample response block (see cj.py's docstring for why that
# sample looks like a documentation rendering artifact).
FLAT_RESPONSE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<cj-api>
    <links total-matched="1" records-returned="1" page-number="1">
        <link>
            <advertiser-id>4347393</advertiser-id>
            <advertiser-name>Booking.com Spain and Portugal</advertiser-name>
            <link-id>11470088</link-id>
            <link-name>Book Lisbon hotels</link-name>
            <description>Book Lisbon hotels</description>
            <link-type>Text Link</link-type>
            <destination>https://www.booking.com/city/pt/lisbon.html</destination>
            <clickUrl>https://www.tkqlhce.com/click-3074780-11470088</clickUrl>
            <relationship-status>joined</relationship-status>
            <targeted-countries>Portugal, Spain</targeted-countries>
        </link>
    </links>
</cj-api>"""

# CJ's documented sample has this exact double-nested shape (copied
# verbatim, minus the html/js payloads for brevity) - tests that the
# defensive parser survives it too, whichever shape turns out to be real.
NESTED_RESPONSE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<cj-api>
    <links total-matched="1" records-returned="1" page-number="1">
        <link>
            <link>
                <advertiser-id>4347393</advertiser-id>
                <advertiser-name>Booking.com Spain and Portugal</advertiser-name>
            </link>
            <destination>https://www.booking.com/city/pt/lisbon.html</destination>
            <link-id>11470088</link-id>
            <link-name>Book Lisbon hotels</link-name>
            <clickUrl>https://www.tkqlhce.com/click-3074780-11470088</clickUrl>
            <targeted-countries>null</targeted-countries>
        </link>
    </links>
</cj-api>"""


@override_settings(CJ_API_TOKEN="test-token", CJ_WEBSITE_ID="12345")
class CJAffiliateProviderTests(TestCase):
    def setUp(self):
        self.provider = CJAffiliateProvider()

    def test_requires_at_least_one_filter(self):
        with self.assertRaises(ValueError):
            self.provider.search_links()

    @patch("integrations.affiliates.cj.requests.get")
    def test_parses_a_flat_response(self, mock_get):
        mock_get.return_value = Mock(text=FLAT_RESPONSE_XML, raise_for_status=Mock())

        results = self.provider.search_links(keywords="Lisbon")

        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertEqual(result.network, "cj")
        self.assertEqual(result.link_id, "11470088")
        self.assertEqual(result.advertiser_id, "4347393")
        self.assertEqual(result.tracking_url, "https://www.tkqlhce.com/click-3074780-11470088")
        self.assertEqual(result.targeted_countries, ["Portugal", "Spain"])

    @patch("integrations.affiliates.cj.requests.get")
    def test_parses_the_nested_shape_from_cjs_own_docs_sample(self, mock_get):
        mock_get.return_value = Mock(text=NESTED_RESPONSE_XML, raise_for_status=Mock())

        results = self.provider.search_links(keywords="Lisbon")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].link_id, "11470088")
        self.assertEqual(results[0].targeted_countries, [])

    @patch("integrations.affiliates.cj.requests.get")
    def test_no_matches_returns_empty_list_not_a_fabricated_result(self, mock_get):
        empty_xml = (
            '<?xml version="1.0"?><cj-api>'
            '<links total-matched="0" records-returned="0" page-number="1"></links>'
            "</cj-api>"
        )
        mock_get.return_value = Mock(text=empty_xml, raise_for_status=Mock())

        results = self.provider.search_links(keywords="Nowhereland")

        self.assertEqual(results, [])

    @patch("integrations.affiliates.cj.requests.get")
    def test_sends_the_correct_auth_header_and_params(self, mock_get):
        mock_get.return_value = Mock(text=FLAT_RESPONSE_XML, raise_for_status=Mock())

        self.provider.search_links(keywords="Lisbon", targeted_country="PT")

        _, kwargs = mock_get.call_args
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-token")
        self.assertEqual(kwargs["params"]["website-id"], "12345")
        self.assertEqual(kwargs["params"]["keywords"], "Lisbon")
        self.assertEqual(kwargs["params"]["targeted-country"], "PT")

    @patch("integrations.affiliates.cj.requests.get")
    def test_network_failure_raises_affiliate_network_error(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("boom")

        with self.assertRaises(AffiliateNetworkError):
            self.provider.search_links(keywords="Lisbon")

    @patch("integrations.affiliates.cj.requests.get")
    def test_malformed_response_raises_affiliate_network_error(self, mock_get):
        mock_get.return_value = Mock(text="not xml at all <<<", raise_for_status=Mock())

        with self.assertRaises(AffiliateNetworkError):
            self.provider.search_links(keywords="Lisbon")

    @override_settings(CJ_API_TOKEN="")
    def test_missing_token_raises_improperly_configured(self):
        with self.assertRaises(ImproperlyConfigured):
            self.provider.search_links(keywords="Lisbon")

    @override_settings(CJ_WEBSITE_ID="")
    def test_missing_website_id_raises_improperly_configured(self):
        with self.assertRaises(ImproperlyConfigured):
            self.provider.search_links(keywords="Lisbon")


class AffiliateProviderFactoryTests(TestCase):
    def test_unset_provider_raises_a_friendly_error(self):
        with self.assertRaises(ImproperlyConfigured):
            get_affiliate_network_provider()

    @override_settings(AFFILIATE_PROVIDER="not-a-real-provider")
    def test_unknown_provider_raises(self):
        with self.assertRaises(ImproperlyConfigured):
            get_affiliate_network_provider()

    @override_settings(AFFILIATE_PROVIDER="cj")
    def test_cj_provider_resolves(self):
        provider = get_affiliate_network_provider()

        self.assertIsInstance(provider, CJAffiliateProvider)
