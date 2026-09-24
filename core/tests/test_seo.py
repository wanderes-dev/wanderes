import re

from django.test import TestCase, override_settings

from users.models import User


class RobotsTxtTests(TestCase):
    def test_disallows_private_login_gated_and_api_paths(self):
        response = self.client.get("/robots.txt")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/plain")
        content = response.content.decode()
        for path in [
            "/admin/",
            "/users/account/",
            "/users/profile/",
            "/trips/",
            "/api/",
            "/travel/",
            "/analytics/",
        ]:
            self.assertIn(f"Disallow: {path}", content)

    def test_points_to_the_canonical_sitemap_url(self):
        response = self.client.get("/robots.txt")

        self.assertIn("Sitemap: https://www.wanderes.com/sitemap.xml", response.content.decode())


class SitemapXmlTests(TestCase):
    def test_lists_the_genuinely_public_pages(self):
        response = self.client.get("/sitemap.xml")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/xml")
        content = response.content.decode()
        self.assertIn("<loc>https://www.wanderes.com/</loc>", content)

    def test_never_lists_login_gated_pages(self):
        response = self.client.get("/sitemap.xml")

        content = response.content.decode()
        self.assertNotIn("/trips/", content)
        self.assertNotIn("/users/account/", content)
        self.assertNotIn("/users/profile/", content)

    def test_never_lists_internal_or_non_content_routes(self):
        # _SITEMAP_ENTRIES is a hand-curated allowlist, not a dump of
        # every urlpattern - this locks that in as a regression guard,
        # not just a design intent in a comment. Covers each category
        # the sitemap must never expose: auth flows, staff-only tools,
        # API/health endpoints, and logout.
        response = self.client.get("/sitemap.xml")

        content = response.content.decode()
        for path in [
            "/users/login/",
            "/users/register/",
            "/users/logout/",
            "/admin/",
            "/analytics/",
            "/travel/",
            "/api/",
            "/health/",
        ]:
            self.assertNotIn(path, content)

    def test_chat_is_not_listed(self):
        # /chat/ is publicly accessible and indexable (see
        # RobotsMetaTagTests below - still index,follow), but it's an
        # interactive product route the traveler is sent into, not an
        # organic search landing page - deliberately excluded from the
        # sitemap itself (2026-09-24, direct instruction), independent
        # of whether it's otherwise crawlable.
        response = self.client.get("/sitemap.xml")

        self.assertNotIn("/chat/", response.content.decode())

    def test_entries_have_no_priority_or_changefreq(self):
        # Neither was backed by a real signal (an actual change cadence,
        # a deliberate ranking-priority decision) - just a plausible-
        # looking guess (2026-09-24, direct instruction to remove them).
        response = self.client.get("/sitemap.xml")

        content = response.content.decode()
        self.assertNotIn("<priority>", content)
        self.assertNotIn("<changefreq>", content)

    def test_never_leaks_a_non_production_domain(self):
        # Every <loc> must be built from SITE_DOMAIN alone - never the
        # host that actually served the request (a Render-assigned
        # hostname, a non-www apex, or a local/dev host), which
        # SiteDomainOverrideTests below already proves structurally.
        # This is the direct, literal regression guard: whatever domain
        # served this test request, it must never show up in the body.
        response = self.client.get("/sitemap.xml", HTTP_HOST="testserver")

        content = response.content.decode()
        self.assertNotIn("testserver", content)
        self.assertNotIn("onrender.com", content)
        # Not a bare "http://" ban - the XML namespace URI itself is
        # legitimately http:// per the sitemaps.org protocol spec, unrelated
        # to page URLs. Checking every <loc> specifically instead.
        locations = re.findall(r"<loc>(.*?)</loc>", content)
        self.assertTrue(locations)
        for location in locations:
            self.assertTrue(location.startswith("https://www.wanderes.com"))


class CanonicalUrlTests(TestCase):
    """The canonical/OG/sitemap domain must always be
    settings.SITE_DOMAIN, never whatever host actually served the request
    - the live service is reachable under more than one hostname."""

    def test_canonical_link_matches_site_domain_setting(self):
        response = self.client.get("/")

        self.assertContains(response, '<link rel="canonical" href="https://www.wanderes.com/">')

    def test_chat_page_canonical_link_includes_its_own_path(self):
        response = self.client.get("/chat/")

        self.assertContains(
            response, '<link rel="canonical" href="https://www.wanderes.com/chat/">'
        )


class RobotsMetaTagTests(TestCase):
    """Every login-gated, user-specific page gets an explicit noindex -
    real SEO value there is zero, and a crawler hitting one
    unauthenticated would only ever see a login redirect anyway."""

    def setUp(self):
        self.user = User.objects.create_user(email="seo-tester@example.com", password="testpass123")

    def test_public_pages_are_indexable_by_default(self):
        for path in ["/", "/chat/"]:
            response = self.client.get(path)
            self.assertContains(response, 'name="robots" content="index, follow"')

    def test_login_gated_pages_are_noindexed(self):
        self.client.force_login(self.user)

        for path in ["/trips/", "/users/account/", "/users/profile/"]:
            response = self.client.get(path)
            self.assertContains(response, 'name="robots" content="noindex, nofollow"')


class StructuredDataTests(TestCase):
    def test_landing_page_includes_organization_json_ld(self):
        response = self.client.get("/")

        self.assertContains(response, '"@type": "Organization"')
        self.assertContains(response, '"name": "Wanderes"')
        self.assertContains(response, '"url": "https://www.wanderes.com/"')

    def test_landing_page_includes_webapplication_json_ld(self):
        response = self.client.get("/")

        self.assertContains(response, '"@type": "WebApplication"')
        self.assertContains(response, '"applicationCategory": "TravelApplication"')
        self.assertContains(response, '"operatingSystem": "Web"')
        self.assertContains(response, '"url": "https://www.wanderes.com/"')


class SocialPreviewImageTests(TestCase):
    """og:image/twitter:image must be an absolute URL (per spec) built
    from SITE_DOMAIN, same reasoning as canonical_url - and must point at
    a real, existing static asset, never a fabricated path."""

    def test_og_and_twitter_image_point_at_the_real_logo_asset(self):
        response = self.client.get("/")

        self.assertContains(
            response, '<meta property="og:image" content="https://www.wanderes.com/static/img/logo.png">'
        )
        self.assertContains(
            response, '<meta name="twitter:image" content="https://www.wanderes.com/static/img/logo.png">'
        )


class LandingPageTitleAndDescriptionTests(TestCase):
    """The homepage title/description should say plainly what Wanderes
    is - an AI travel advisor - not just its brand name, since that's
    the actual concept a search query would match on."""

    def test_title_names_the_product_category(self):
        response = self.client.get("/")

        self.assertContains(
            response, "<title>Wanderes — AI Travel Advisor & Destination Finder</title>"
        )

    def test_meta_description_covers_the_core_concepts(self):
        response = self.client.get("/")
        content = response.content.decode()

        concepts = ["AI travel advisor", "travel destinations", "budget", "climate", "travel style"]
        for concept in concepts:
            self.assertIn(concept, content)


@override_settings(SITE_DOMAIN="example-alias.test")
class SiteDomainOverrideTests(TestCase):
    """Confirms SITE_DOMAIN is actually read from settings at request time,
    not hardcoded anywhere it's used for canonical/sitemap/robots URLs."""

    def test_canonical_link_follows_a_non_default_site_domain(self):
        response = self.client.get("/")

        self.assertContains(response, 'href="https://example-alias.test/"')

    def test_sitemap_follows_a_non_default_site_domain(self):
        response = self.client.get("/sitemap.xml")

        self.assertIn("https://example-alias.test/", response.content.decode())
