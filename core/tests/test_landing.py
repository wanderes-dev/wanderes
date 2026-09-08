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
        # not just a couple of generic, context-free bullets. Reworded
        # 2026-09-09 to demonstrate multiple concrete dimensions (climate,
        # interests, budget, pace) plus an honest, specific tradeoff tied
        # to a stated preference, rather than generic positive badges -
        # "Tradeoff:" became its own "Worth knowing" section to match.
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
        self.assertContains(response, "Why this fits you")
        self.assertContains(response, "Worth knowing")
        self.assertContains(response, "Strong fit for food and nature")
        self.assertContains(response, "Comfortable for your budget")
        self.assertContains(response, "Matches your preferred travel pace")

    def test_preview_card_pins_to_bali_when_present(self):
        # 2026-09-09: the preview card's copy now names Bali specifically
        # ("Popular parts of Bali can get busy...") - it must always show
        # the real Bali row, not whatever beach/nature destination
        # happens to sort first by id, or the hardcoded copy and the
        # destination shown could mismatch.
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
        Destination.objects.create(
            slug="bali-id",
            name="Bali",
            country="Indonesia",
            latitude=-8.34,
            longitude=115.09,
            trip_type="beach",
            cost_of_living=1,
            best_season="Apr-Oct",
            worst_season="Dec-Feb",
            short_description="A real beach destination.",
            points_of_interest=[],
        )

        response = self.client.get("/")

        self.assertContains(response, "Popular parts of Bali can get busy")

    def test_landing_copy_does_not_claim_live_travel_inventory(self):
        # Direct product constraint: Wanderes has real climate/destination
        # data, but no production hotel/flight inventory yet (Priceline/
        # Booking.com/Agoda integrations are pursued but not live) - the
        # landing page must never read as promising live prices,
        # availability, or bookable inventory it can't actually back up.
        response = self.client.get("/")
        content = response.content.decode()

        unsupported_claims = (
            "live price",
            "live prices",
            "live availability",
            "book now",
            "real-time price",
        )
        for claim in unsupported_claims:
            self.assertNotIn(claim, content.lower())
        self.assertContains(
            response,
            "Real recommendations grounded in destination, climate, and travel-cost data",
        )
