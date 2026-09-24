"""Tests for analytics.acquisition - UTM/referrer capture, first/latest
touch persistence, sanitization. Downstream funnel-event attachment
(travel_question_submitted/recommendation_generated/
accommodation_outbound_click carrying the snapshot) is tested in
ai/tests/test_views.py, where those events are actually fired."""

from django.test import RequestFactory, TestCase

from analytics.acquisition import _classify_referrer, _clean_utm_value, _extract_utms
from analytics.models import Event
from users.models import User


class CleanUtmValueTests(TestCase):
    def test_passes_through_a_normal_value(self):
        self.assertEqual(_clean_utm_value("warm_november"), "warm_november")

    def test_none_and_empty_string_both_become_none(self):
        self.assertIsNone(_clean_utm_value(None))
        self.assertIsNone(_clean_utm_value(""))

    def test_strips_html_script_characters(self):
        self.assertEqual(_clean_utm_value("<script>alert(1)</script>"), "scriptalert1script")

    def test_strips_quotes_and_semicolons(self):
        self.assertEqual(_clean_utm_value("a\"b';c"), "abc")

    def test_a_value_that_is_entirely_disallowed_characters_becomes_none(self):
        self.assertIsNone(_clean_utm_value("<<<>>>"))

    def test_truncates_to_the_max_length(self):
        result = _clean_utm_value("a" * 500)

        self.assertEqual(len(result), 100)

    def test_allows_spaces_dashes_underscores_dots_plus(self):
        self.assertEqual(_clean_utm_value("a-b_c.d+e f"), "a-b_c.d+e f")


class ExtractUtmsTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_all_five_params_captured(self):
        request = self.factory.get(
            "/?utm_source=tiktok&utm_medium=organic_social&utm_campaign=warm_november"
            "&utm_content=video1&utm_term=beach"
        )

        self.assertEqual(
            _extract_utms(request),
            {
                "source": "tiktok",
                "medium": "organic_social",
                "campaign": "warm_november",
                "content": "video1",
                "term": "beach",
            },
        )

    def test_partial_utm_set_leaves_missing_fields_none(self):
        request = self.factory.get("/?utm_source=instagram")

        result = _extract_utms(request)

        self.assertEqual(result["source"], "instagram")
        self.assertIsNone(result["medium"])
        self.assertIsNone(result["campaign"])

    def test_no_utm_params_returns_none(self):
        request = self.factory.get("/")

        self.assertIsNone(_extract_utms(request))

    def test_oversized_value_is_truncated(self):
        request = self.factory.get("/?utm_campaign=" + "x" * 500)

        result = _extract_utms(request)

        self.assertEqual(len(result["campaign"]), 100)

    def test_xss_like_value_is_sanitized(self):
        request = self.factory.get("/?utm_campaign=%3Cscript%3Ealert(1)%3C/script%3E")

        result = _extract_utms(request)

        self.assertNotIn("<", result["campaign"])
        self.assertNotIn(">", result["campaign"])


class ClassifyReferrerTests(TestCase):
    def test_no_referrer_is_direct(self):
        self.assertEqual(_classify_referrer(None), (None, "direct"))
        self.assertEqual(_classify_referrer(""), (None, "direct"))

    def test_google_is_organic_search(self):
        self.assertEqual(
            _classify_referrer("https://www.google.com/search?q=travel"),
            ("google", "organic_search"),
        )

    def test_bing_is_organic_search(self):
        self.assertEqual(
            _classify_referrer("https://www.bing.com/search?q=travel"),
            ("bing", "organic_search"),
        )

    def test_instagram_is_organic_social(self):
        self.assertEqual(
            _classify_referrer("https://www.instagram.com/"), ("instagram", "organic_social")
        )

    def test_tiktok_is_organic_social(self):
        self.assertEqual(
            _classify_referrer("https://www.tiktok.com/@someone/video/123"),
            ("tiktok", "organic_social"),
        )

    def test_unknown_site_is_a_generic_referral(self):
        source, medium = _classify_referrer("https://some-travel-blog.example/post")

        self.assertEqual(source, "some-travel-blog.example")
        self.assertEqual(medium, "referral")

    def test_garbage_referrer_falls_back_to_direct(self):
        source, medium = _classify_referrer("not-a-url-at-all")

        self.assertIsNone(source)
        self.assertEqual(medium, "direct")


class CaptureAcquisitionTests(TestCase):
    """Driven through core.views.landing (the real integration point) -
    capture_acquisition() is never called any other way in the app."""

    def test_first_visit_with_utms_captures_first_touch(self):
        response = self.client.get(
            "/",
            {
                "utm_source": "tiktok",
                "utm_medium": "organic_social",
                "utm_campaign": "warm_november",
                "utm_content": "video1",
            },
        )

        self.assertEqual(response.status_code, 200)
        acquisition = self.client.session["acquisition"]
        self.assertEqual(
            acquisition["first_touch"],
            {
                "source": "tiktok",
                "medium": "organic_social",
                "campaign": "warm_november",
                "content": "video1",
                "term": None,
            },
        )
        self.assertEqual(acquisition["latest_touch"], acquisition["first_touch"])

        event = Event.objects.get(event_type="acquisition_captured")
        self.assertEqual(event.metadata["touch_type"], "first")
        self.assertEqual(event.metadata["source"], "tiktok")
        self.assertIsNone(event.user)
        self.assertIsNotNone(event.anonymized_ip)
        self.assertIsNotNone(event.conversation_key)

    def test_first_visit_without_utms_uses_referrer_classification(self):
        self.client.get("/", HTTP_REFERER="https://www.google.com/search?q=travel+ideas")

        acquisition = self.client.session["acquisition"]
        self.assertEqual(acquisition["first_touch"]["source"], "google")
        self.assertEqual(acquisition["first_touch"]["medium"], "organic_search")

    def test_first_visit_with_no_utms_or_referrer_is_direct(self):
        self.client.get("/")

        acquisition = self.client.session["acquisition"]
        self.assertIsNone(acquisition["first_touch"]["source"])
        self.assertEqual(acquisition["first_touch"]["medium"], "direct")

    def test_refresh_of_the_same_campaign_url_does_not_duplicate_the_event(self):
        params = {"utm_source": "tiktok", "utm_campaign": "warm_november"}
        self.client.get("/", params)
        self.client.get("/", params)

        self.assertEqual(Event.objects.filter(event_type="acquisition_captured").count(), 1)

    def test_internal_navigation_does_not_overwrite_or_re_fire_first_touch(self):
        self.client.get("/", {"utm_source": "tiktok", "utm_campaign": "warm_november"})
        self.client.get("/chat/")

        acquisition = self.client.session["acquisition"]
        self.assertEqual(acquisition["first_touch"]["source"], "tiktok")
        self.assertEqual(Event.objects.filter(event_type="acquisition_captured").count(), 1)

    def test_a_new_campaign_visit_updates_latest_touch_not_first_touch(self):
        self.client.get("/", {"utm_source": "tiktok", "utm_campaign": "warm_november"})
        self.client.get("/", {"utm_source": "google", "utm_campaign": "brand_search"})

        acquisition = self.client.session["acquisition"]
        self.assertEqual(acquisition["first_touch"]["source"], "tiktok")
        self.assertEqual(acquisition["latest_touch"]["source"], "google")

        events = list(
            Event.objects.filter(event_type="acquisition_captured").order_by("created_at")
        )
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].metadata["touch_type"], "first")
        self.assertEqual(events[1].metadata["touch_type"], "latest")

    def test_malformed_or_oversized_utm_values_are_sanitized_before_storage(self):
        self.client.get(
            "/", {"utm_source": "tiktok", "utm_campaign": "<script>alert(1)</script>" + "x" * 200}
        )

        acquisition = self.client.session["acquisition"]
        campaign = acquisition["first_touch"]["campaign"]
        self.assertNotIn("<", campaign)
        self.assertNotIn(">", campaign)
        self.assertLessEqual(len(campaign), 100)

    def test_authenticated_visitor_gets_a_user_scoped_event(self):
        user = User.objects.create_user(email="traveler@example.com", password="testpass123")
        self.client.force_login(user)

        self.client.get("/", {"utm_source": "tiktok", "utm_campaign": "warm_november"})

        event = Event.objects.get(event_type="acquisition_captured")
        self.assertEqual(event.user, user)
        self.assertIsNone(event.anonymized_ip)
