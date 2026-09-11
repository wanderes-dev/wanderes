from django.http import QueryDict
from django.test import TestCase
from django.urls import reverse

from analytics.models import Event
from travel.models import Destination
from trips.models import Trip
from users.models import User


class TripViewsTests(TestCase):
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

    def test_list_requires_login(self):
        response = self.client.get(reverse("trips:trip-list"))

        self.assertEqual(response.status_code, 302)

    def test_create_requires_login_and_redirects_with_next(self):
        # This is the login gate an anonymous chat visitor actually hits -
        # the chat page always renders a "Save this trip" link, gated only
        # here at trip_create, not earlier.
        create_url = reverse("trips:trip-create") + f"?destination={self.destination.slug}"

        response = self.client.get(create_url)

        querystring = QueryDict(mutable=True)
        querystring["next"] = create_url
        expected_redirect = f"{reverse('users:login')}?{querystring.urlencode(safe='/')}"
        self.assertRedirects(response, expected_redirect, fetch_redirect_response=False)

    def test_create_saves_trip_for_current_user(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("trips:trip-create"),
            {
                "name": "Summer in Lisbon",
                "destination": self.destination.pk,
                "status": "planned",
                "start_date": "",
                "end_date": "",
            },
        )

        trip = Trip.objects.get(user=self.user)
        self.assertRedirects(response, reverse("trips:trip-detail", args=[trip.pk]))
        self.assertEqual(trip.name, "Summer in Lisbon")
        self.assertEqual(trip.destination, self.destination)
        self.assertTrue(
            Event.objects.filter(
                user=self.user, event_type="trip_created", metadata__source="form"
            ).exists()
        )

    def test_create_from_chat_recommendation_records_that_source(self):
        # Distinguishes the "Save this trip" chat flow from other entry
        # points (e.g. trip_list.html's plain "Create a new trip" link) -
        # source is round-tripped through a hidden form field since GET's
        # ?source= wouldn't otherwise survive the POST.
        self.client.force_login(self.user)
        get_response = self.client.get(
            reverse("trips:trip-create")
            + f"?destination={self.destination.slug}&source=chat_recommendation"
        )
        self.assertContains(get_response, 'name="source" value="chat_recommendation"')

        self.client.post(
            reverse("trips:trip-create"),
            {
                "name": "Summer in Lisbon",
                "destination": self.destination.pk,
                "status": "planned",
                "start_date": "",
                "end_date": "",
                "source": "chat_recommendation",
            },
        )

        self.assertTrue(
            Event.objects.filter(
                user=self.user,
                event_type="trip_created",
                metadata__source="chat_recommendation",
            ).exists()
        )

    def test_create_ignores_an_unrecognized_source_value(self):
        # An arbitrary echoed string must not land verbatim in analytics
        # metadata - only the one allow-listed value is honored.
        self.client.force_login(self.user)

        self.client.post(
            reverse("trips:trip-create"),
            {
                "name": "Summer in Lisbon",
                "destination": self.destination.pk,
                "status": "planned",
                "start_date": "",
                "end_date": "",
                "source": "<script>totally-not-a-real-source</script>",
            },
        )

        event = Event.objects.get(user=self.user, event_type="trip_created")
        self.assertEqual(event.metadata["source"], "form")

    def test_create_prefills_destination_from_query_param(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("trips:trip-create") + f"?destination={self.destination.slug}"
        )

        self.assertContains(response, f'value="{self.destination.pk}" selected')

    def test_list_only_shows_own_trips(self):
        Trip.objects.create(user=self.other_user, destination=self.destination)
        self.client.force_login(self.user)

        response = self.client.get(reverse("trips:trip-list"))

        self.assertEqual(list(response.context["trips"]), [])

    def test_cannot_view_another_users_trip(self):
        trip = Trip.objects.create(user=self.other_user, destination=self.destination)
        self.client.force_login(self.user)

        response = self.client.get(reverse("trips:trip-detail", args=[trip.pk]))

        self.assertEqual(response.status_code, 404)

    def test_edit_updates_own_trip(self):
        trip = Trip.objects.create(user=self.user, destination=self.destination, name="Old name")
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("trips:trip-edit", args=[trip.pk]),
            {
                "name": "New name",
                "destination": self.destination.pk,
                "status": "completed",
                "start_date": "",
                "end_date": "",
            },
        )

        self.assertRedirects(response, reverse("trips:trip-detail", args=[trip.pk]))
        trip.refresh_from_db()
        self.assertEqual(trip.name, "New name")
        self.assertEqual(trip.status, "completed")

    def test_cannot_edit_another_users_trip(self):
        trip = Trip.objects.create(user=self.other_user, destination=self.destination)
        self.client.force_login(self.user)

        response = self.client.get(reverse("trips:trip-edit", args=[trip.pk]))

        self.assertEqual(response.status_code, 404)

    def test_delete_removes_own_trip(self):
        trip = Trip.objects.create(user=self.user, destination=self.destination)
        self.client.force_login(self.user)

        response = self.client.post(reverse("trips:trip-delete", args=[trip.pk]))

        self.assertRedirects(response, reverse("trips:trip-list"))
        self.assertFalse(Trip.objects.filter(pk=trip.pk).exists())

    def test_cannot_delete_another_users_trip(self):
        trip = Trip.objects.create(user=self.other_user, destination=self.destination)
        self.client.force_login(self.user)

        response = self.client.post(reverse("trips:trip-delete", args=[trip.pk]))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(Trip.objects.filter(pk=trip.pk).exists())
