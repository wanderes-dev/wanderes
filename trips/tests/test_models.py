from datetime import timedelta

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from travel.models import Destination
from trips.models import Feedback, Trip, TripAccommodation, TripFlight
from users.models import User


class TripModelsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="traveler@example.com", password="testpass123")
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
            points_of_interest=["Belem Tower"],
        )

    def test_trip_with_flight_and_accommodation(self):
        trip = Trip.objects.create(user=self.user, destination=self.destination, status="planned")
        flight = TripFlight.objects.create(
            trip=trip,
            flight_number="TP123",
            airline="TAP",
            departure_at=timezone.now(),
            duration=timedelta(hours=9),
            leg_order=1,
            price="450.00",
            price_rate=3,
            rating=8,
        )
        accommodation = TripAccommodation.objects.create(
            trip=trip,
            name="Hotel Central",
            address="Rua Augusta, Lisbon",
            price="120.00",
            price_rate=2,
            rating=9,
        )

        self.assertIn(flight, trip.flights.all())
        self.assertIn(accommodation, trip.accommodations.all())

    def test_feedback_requires_destination_or_trip(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Feedback.objects.create(user=self.user, rating=7)

    def test_feedback_with_destination_only_is_valid(self):
        feedback = Feedback.objects.create(user=self.user, destination=self.destination, rating=9)

        self.assertEqual(feedback.destination, self.destination)
        self.assertIsNone(feedback.trip)
