from unittest.mock import patch

from django.test import RequestFactory, TestCase

from analytics.models import Event
from analytics.services import _anonymize_ip, record_event
from users.models import User


class AnonymizeIpTests(TestCase):
    def test_zeroes_last_ipv4_octet(self):
        self.assertEqual(_anonymize_ip("203.0.113.42"), "203.0.113.0")

    def test_masks_ipv6_to_48_bit_prefix(self):
        self.assertEqual(_anonymize_ip("2001:db8:1234:5678::1"), "2001:db8:1234::")

    def test_invalid_address_returns_none(self):
        self.assertIsNone(_anonymize_ip("not-an-ip"))

    def test_none_input_returns_none(self):
        self.assertIsNone(_anonymize_ip(None))


class RecordEventTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="traveler@example.com", password="testpass123")
        self.factory = RequestFactory()

    def test_authenticated_event_stores_user_not_ip(self):
        record_event("user_registered", user=self.user)

        event = Event.objects.get()
        self.assertEqual(event.user, self.user)
        self.assertIsNone(event.anonymized_ip)

    def test_anonymous_event_stores_anonymized_ip_not_raw(self):
        request = self.factory.post("/api/v1/recommendations/")
        request.META["REMOTE_ADDR"] = "203.0.113.42"

        record_event("travel_question_submitted", user=None, request=request)

        event = Event.objects.get()
        self.assertIsNone(event.user)
        self.assertEqual(event.anonymized_ip, "203.0.113.0")

    def test_anonymous_event_without_request_is_skipped(self):
        record_event("travel_question_submitted", user=None, request=None)

        self.assertFalse(Event.objects.exists())

    def test_unknown_event_type_is_skipped(self):
        record_event("not_a_real_event", user=self.user)

        self.assertFalse(Event.objects.exists())

    def test_metadata_is_stored(self):
        record_event("trip_created", user=self.user, metadata={"destination_slug": "lisbon-pt"})

        event = Event.objects.get()
        self.assertEqual(event.metadata, {"destination_slug": "lisbon-pt"})

    def test_failure_is_swallowed_not_raised(self):
        with patch("analytics.services.Event.objects.create", side_effect=RuntimeError("boom")):
            record_event("user_registered", user=self.user)  # must not raise

        self.assertFalse(Event.objects.exists())
