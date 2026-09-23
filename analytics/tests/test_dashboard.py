import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from analytics.models import DailyProductMetrics, Event
from travel.models import Destination
from users.models import User


class DashboardAccessTests(TestCase):
    def test_anonymous_visitor_is_redirected_to_login(self):
        response = self.client.get(reverse("analytics:dashboard"))

        self.assertEqual(response.status_code, 302)

    def test_non_staff_user_is_redirected(self):
        user = User.objects.create_user(email="traveler@example.com", password="testpass123")
        self.client.force_login(user)

        response = self.client.get(reverse("analytics:dashboard"))

        self.assertEqual(response.status_code, 302)

    def test_staff_user_can_view_the_dashboard(self):
        staff = User.objects.create_user(
            email="staff@example.com", password="testpass123", is_staff=True
        )
        self.client.force_login(staff)

        response = self.client.get(reverse("analytics:dashboard"))

        self.assertEqual(response.status_code, 200)


class DashboardRenderingTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            email="staff@example.com", password="testpass123", is_staff=True
        )
        self.client.force_login(self.staff)

    def test_renders_with_no_data_yet(self):
        response = self.client.get(reverse("analytics:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No daily metrics yet")

    def test_sections_use_the_styled_card_class_not_the_bare_profile_section(self):
        # Regression guard for the "layout is quite bad" report - plain
        # .profile-section reads as an unstyled wall of text on a
        # data-dense page like this. Locks in .dashboard-section (real
        # card styling, see static/css/main.css) so a future edit can't
        # quietly revert to the bare class.
        response = self.client.get(reverse("analytics:dashboard"))
        content = response.content.decode()

        self.assertIn('class="dashboard-section"', content)
        self.assertNotIn('class="profile-section"', content)

    def test_renders_daily_metrics_row(self):
        DailyProductMetrics.objects.create(
            date="2026-09-01",
            conversations_started=5,
            messages_sent=12,
            ai_latency_p95_ms="842.3",
        )

        response = self.client.get(reverse("analytics:dashboard"))

        self.assertContains(response, "2026-09-01")
        self.assertContains(response, "842.3")

    def test_destination_performance_includes_accommodation_clicks(self):
        Destination.objects.create(
            slug="bali-id",
            name="Bali",
            country="Indonesia",
            latitude="-8.34000",
            longitude="115.09000",
            trip_type="beach",
            cost_of_living=1,
            best_season="Apr-Oct",
            worst_season="Dec-Mar",
            short_description="A tropical island.",
            points_of_interest=[],
        )
        traveler = User.objects.create_user(email="traveler@example.com", password="x")
        key = f"chat-history:user:{traveler.pk}"
        base = timezone.now() - datetime.timedelta(hours=1)
        recommended = Event.objects.create(
            event_type="recommendation_generated",
            user=traveler,
            conversation_key=key,
            metadata={"destination_slugs": ["bali-id"]},
        )
        Event.objects.filter(pk=recommended.pk).update(created_at=base)
        clicked = Event.objects.create(
            event_type="accommodation_outbound_click",
            user=traveler,
            conversation_key=key,
            metadata={"destination_slug": "bali-id", "provider": "booking_com"},
        )
        # created_at uses auto_now_add=True, so it has to be moved forward
        # of the recommendation via a bare .update() (not .save(), which
        # auto_now_add would silently ignore anyway) - the correlation this
        # is testing depends on the click strictly following the
        # recommendation in time, not just insertion order.
        Event.objects.filter(pk=clicked.pk).update(
            created_at=base + datetime.timedelta(minutes=1)
        )

        response = self.client.get(reverse("analytics:dashboard"))
        content = response.content.decode()

        self.assertContains(response, "Stays clicked")
        self.assertContains(response, "Bali")
        # times_accommodation_clicked=1 shows up as its own <td> next to
        # Bali's row - just checking "1" appears anywhere would be
        # meaningless noise on a numbers-heavy page.
        bali_row_start = content.index("Bali")
        bali_row_end = content.index("</tr>", bali_row_start)
        self.assertIn(">1<", content[bali_row_start:bali_row_end])
