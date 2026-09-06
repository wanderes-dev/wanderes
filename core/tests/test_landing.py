from django.test import TestCase

from travel.models import Destination


class LandingPageTests(TestCase):
    def test_root_renders_landing_page_not_a_redirect(self):
        # 2026-09-01, direct user request: a first-time visitor should see
        # a real landing page, not be redirected straight into /chat/
        # (the previous behavior - replaces test_root_redirect.py).
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/landing.html")

    def test_landing_page_shows_real_destinations_only(self):
        destination = Destination.objects.create(
            slug="test-destination",
            name="Test Destination",
            country="Testland",
            latitude=1.0,
            longitude=1.0,
            trip_type="beach",
            cost_of_living=2,
            best_season="Jan-Dec",
            worst_season="None",
            short_description="A test destination.",
            points_of_interest=[],
        )

        response = self.client.get("/")

        self.assertContains(response, destination.name)
        self.assertContains(response, destination.country)

    def test_landing_page_links_to_chat(self):
        response = self.client.get("/")

        self.assertContains(response, '/chat/')

    def test_preview_card_demonstrates_fit_reasoning(self):
        # 2026-09-06, direct request: the "see it in action" example should
        # demonstrate signals (climate/style/budget/pace fit and a tradeoff),
        # not just a couple of generic, context-free bullets.
        Destination.objects.create(
            slug="test-beach-destination",
            name="Test Beach Destination",
            country="Testland",
            latitude=1.0,
            longitude=1.0,
            trip_type="beach",
            cost_of_living=2,
            best_season="Jan-Dec",
            worst_season="None",
            short_description="A test destination.",
            points_of_interest=[],
        )

        response = self.client.get("/")

        self.assertContains(response, "Strong match for your trip")
        self.assertContains(response, "Tradeoff:")
        self.assertContains(response, "Why this fits you")
