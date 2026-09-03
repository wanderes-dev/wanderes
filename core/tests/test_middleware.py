from django.test import TestCase, override_settings

# ALLOWED_HOSTS must explicitly include every hostname these tests send a
# request to, or Django's own host validation rejects it (DisallowedHost)
# before CanonicalDomainRedirectMiddleware ever runs - this isn't specific
# to the middleware under test, so it's overridden once for the whole
# module rather than per test.
_TEST_ALLOWED_HOSTS = [
    "testserver",
    "wanderes.com",
    "www.wanderes.com",
    "travelagent-web.onrender.com",
    "wanderes-web.onrender.com",
]


@override_settings(ALLOWED_HOSTS=_TEST_ALLOWED_HOSTS, SITE_DOMAIN="wanderes.com")
class CanonicalDomainRedirectMiddlewareTests(TestCase):
    def test_www_redirects_to_the_canonical_apex_domain(self):
        response = self.client.get("/chat/", HTTP_HOST="www.wanderes.com")

        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], "https://wanderes.com/chat/")

    def test_legacy_onrender_hostname_redirects_and_preserves_query_string(self):
        response = self.client.get("/chat/?foo=bar", HTTP_HOST="travelagent-web.onrender.com")

        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], "https://wanderes.com/chat/?foo=bar")

    def test_canonical_host_itself_is_never_redirected(self):
        response = self.client.get("/", HTTP_HOST="wanderes.com")

        self.assertEqual(response.status_code, 200)

    def test_health_check_is_never_redirected_even_on_a_duplicate_host(self):
        # The most important case here: Render's own health check almost
        # certainly hits the service on its own current onrender.com
        # hostname, not wanderes.com - if that host were ever added to the
        # redirect allowlist (or the allowlist logic were ever loosened to
        # "any non-canonical host"), a redirect here instead of a 200 would
        # make Render treat the whole service as down.
        response = self.client.get("/health/", HTTP_HOST="www.wanderes.com")

        self.assertEqual(response.status_code, 200)

    def test_current_render_service_hostname_is_not_in_the_redirect_allowlist(self):
        # Confirms the middleware's allowlist is deliberately narrow - it
        # must never include whatever hostname Render currently assigns
        # the live service, since that's the same hostname its health
        # check almost certainly uses.
        response = self.client.get("/health/", HTTP_HOST="wanderes-web.onrender.com")

        self.assertEqual(response.status_code, 200)
