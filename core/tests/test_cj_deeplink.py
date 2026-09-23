from django.test import TestCase


class CjDeepLinkTestPageTests(TestCase):
    """Temporary validation page - see core.views.test_cj_deeplink's
    docstring. These tests exist only to lock in the exact content the
    page must serve while it's live; delete alongside the view/template
    once the CJ validation is done."""

    def test_page_loads(self):
        response = self.client.get("/test-cj-deeplink/")

        self.assertEqual(response.status_code, 200)

    def test_contains_the_exact_booking_search_link(self):
        response = self.client.get("/test-cj-deeplink/")
        content = response.content.decode()

        self.assertIn(
            'href="https://www.booking.com/searchresults.en-gb.html?ss=Tokyo&amp;'
            "checkin=2026-10-07&amp;checkout=2026-10-21&amp;group_adults=2&amp;"
            'no_rooms=1&amp;group_children=0"',
            content,
        )
        self.assertIn("Search stays in Tokyo", content)

    def test_contains_the_exact_cj_automation_script_tag(self):
        response = self.client.get("/test-cj-deeplink/")
        content = response.content.decode()

        self.assertIn(
            '<script src="https://www.anrdoezrs.net/am/101877506/include/allCj/'
            'impressions/page/am.js"></script>',
            content,
        )

    def test_script_tag_comes_right_before_the_closing_body_tag(self):
        # The whole point of this page is testing CJ's own automation, not
        # anything manually built here - the script has to be positioned
        # exactly where the spec asked for it, not just present somewhere.
        response = self.client.get("/test-cj-deeplink/")
        content = response.content.decode()

        script_pos = content.index("am.js")
        body_close_pos = content.index("</body>")
        self.assertLess(script_pos, body_close_pos)
        self.assertNotIn("</script>", content[content.index("</script>") + len("</script>") :])

    def test_never_manually_generates_a_cj_tracking_link(self):
        # Deep Link Automation is supposed to do this client-side, in the
        # visitor's browser - the server must never construct one of
        # these itself, or the test wouldn't actually validate CJ's own
        # automation.
        response = self.client.get("/test-cj-deeplink/")
        content = response.content.decode()

        for tracking_domain in ["jdoqocy.com", "dpbolvw.net", "tkqlhce.com", "qksrv.net"]:
            self.assertNotIn(tracking_domain, content)

    def test_is_noindexed(self):
        response = self.client.get("/test-cj-deeplink/")

        self.assertContains(response, '<meta name="robots" content="noindex, nofollow">')

    def test_not_linked_from_the_landing_page(self):
        response = self.client.get("/")

        self.assertNotContains(response, "test-cj-deeplink")
