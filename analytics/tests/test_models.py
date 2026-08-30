from django.test import TestCase

from analytics.models import Event
from users.models import User


class EventModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="traveler@example.com", password="testpass123")

    def test_can_create_authenticated_event(self):
        event = Event.objects.create(event_type="user_registered", user=self.user)

        self.assertIsNone(event.anonymized_ip)

    def test_can_create_anonymous_event(self):
        event = Event.objects.create(
            event_type="travel_question_submitted", anonymized_ip="1.2.3.0"
        )

        self.assertIsNone(event.user)

    def test_deleting_user_keeps_event_with_null_user(self):
        # user uses on_delete=SET_NULL specifically so deleting an account
        # doesn't retroactively distort historical aggregate metrics.
        Event.objects.create(event_type="user_registered", user=self.user)

        self.user.delete()

        event = Event.objects.get(event_type="user_registered")
        self.assertIsNone(event.user)
