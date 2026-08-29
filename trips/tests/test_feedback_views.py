from django.test import TestCase
from django.urls import reverse

from travel.models import Destination
from trips.models import Feedback, Trip
from users.models import User


class TripFeedbackViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="traveler@example.com", password="testpass123")
        self.other_user = User.objects.create_user(
            email="other@example.com", password="testpass123"
        )
        self.destination = Destination.objects.create(
            slug="lisbon-pt",
            name="Lisbon",
            country="Portugal",
            latitude="38.72000",
            longitude="-9.14000",
            trip_type="city",
            cost_of_living=3,
            best_season="Mar-Oct",
            worst_season="Dec-Feb",
            short_description="A hilly coastal capital.",
            points_of_interest=[],
        )
        self.trip = Trip.objects.create(user=self.user, destination=self.destination)

    def test_requires_login(self):
        response = self.client.get(reverse("trips:trip-feedback", args=[self.trip.pk]))

        self.assertEqual(response.status_code, 302)

    def test_cannot_leave_feedback_on_another_users_trip(self):
        other_trip = Trip.objects.create(user=self.other_user, destination=self.destination)
        self.client.force_login(self.user)

        response = self.client.get(reverse("trips:trip-feedback", args=[other_trip.pk]))

        self.assertEqual(response.status_code, 404)

    def test_creates_feedback_with_rating_tags_and_comment(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("trips:trip-feedback", args=[self.trip.pk]),
            {
                "rating": 8,
                "tags": ["excellent_food", "too_crowded"],
                "comment": "Loved the food, too many tourists though.",
            },
        )

        self.assertRedirects(response, reverse("trips:trip-detail", args=[self.trip.pk]))
        feedback = Feedback.objects.get(trip=self.trip, user=self.user)
        self.assertEqual(feedback.rating, 8)
        self.assertEqual(feedback.tags, ["excellent_food", "too_crowded"])
        self.assertEqual(feedback.destination, self.destination)
        self.assertEqual(feedback.comment, "Loved the food, too many tourists though.")

    def test_rejects_rating_out_of_range(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("trips:trip-feedback", args=[self.trip.pk]), {"rating": 11, "tags": []}
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Feedback.objects.filter(trip=self.trip).exists())

    def test_resubmitting_updates_existing_feedback_instead_of_duplicating(self):
        self.client.force_login(self.user)
        self.client.post(
            reverse("trips:trip-feedback", args=[self.trip.pk]),
            {"rating": 5, "tags": ["overpriced"], "comment": "First take."},
        )

        self.client.post(
            reverse("trips:trip-feedback", args=[self.trip.pk]),
            {"rating": 9, "tags": ["great_value"], "comment": "Changed my mind."},
        )

        self.assertEqual(Feedback.objects.filter(trip=self.trip, user=self.user).count(), 1)
        feedback = Feedback.objects.get(trip=self.trip, user=self.user)
        self.assertEqual(feedback.rating, 9)
        self.assertEqual(feedback.comment, "Changed my mind.")

    def test_trip_detail_shows_feedback_tag_labels(self):
        Feedback.objects.create(
            user=self.user,
            trip=self.trip,
            destination=self.destination,
            rating=7,
            tags=["excellent_food"],
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("trips:trip-detail", args=[self.trip.pk]))

        self.assertContains(response, "Excellent food")
        self.assertNotContains(response, "excellent_food")
