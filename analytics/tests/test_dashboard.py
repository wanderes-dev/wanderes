from django.test import TestCase
from django.urls import reverse

from analytics.models import DailyProductMetrics
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
        # 2026-09-09, direct live report: the dashboard "loads but the
        # layout is quite bad" - .profile-section alone (a thin divider
        # between stacked form sections) reads as an unstyled wall of
        # text for a data-dense page like this. Locks in the fix
        # (.dashboard-section, a real card with border/shadow/padding -
        # see static/css/main.css) rather than letting a future edit
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
