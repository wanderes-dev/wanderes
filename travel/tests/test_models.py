from django.test import TestCase

from travel.models import Destination


class DestinationTests(TestCase):
    def test_create_destination(self):
        destination = Destination.objects.create(
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
            points_of_interest=["Belem Tower", "Alfama"],
        )

        self.assertEqual(str(destination), "Lisbon, Portugal")
        self.assertEqual(destination.points_of_interest, ["Belem Tower", "Alfama"])
