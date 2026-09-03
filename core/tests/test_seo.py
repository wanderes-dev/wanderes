from django.test import TestCase, override_settings

from users.models import User


class RobotsTxtTests(TestCase):
    def test_disallows_private_login_gated_and_api_paths(self):
        response = self.client.get("/robots.txt")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/plain")
        content = response.content.decode()
        for path in ["/admin/", "/users/account/", "/users/profile/", "/trips/", "/api/"]:
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
        self.assertIn("<loc>https://www.wanderes.com/chat/</loc>", content)

    def test_never_lists_login_gated_pages(self):
        response = self.client.get("/sitemap.xml")

        content = response.content.decode()
        self.assertNotIn("/trips/", content)
        self.assertNotIn("/users/account/", content)
        self.assertNotIn("/users/profile/", content)


class CanonicalUrlTests(TestCase):
    """The canonical/OG/sitemap domain must always be settings.SITE_DOMAIN,
    never whatever host actually served the request - the live service is
    reachable under more than one hostname (2026-09-03, SEO prep)."""

    def test_canonical_link_matches_site_domain_setting(self):
        response = self.client.get("/")

        self.assertContains(response, '<link rel="canonical" href="https://www.wanderes.com/">')

    def test_chat_page_canonical_link_includes_its_own_path(self):
        response = self.client.get("/chat/")

        self.assertContains(
            response, '<link rel="canonical" href="https://www.wanderes.com/chat/">'
        )


class RobotsMetaTagTests(TestCase):
    """The 2026-09-03 SEO pass added an explicit noindex to every
    login-gated, user-specific page - real SEO value there is zero, and a
    crawler hitting one unauthenticated would only ever see a login
    redirect anyway."""

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
