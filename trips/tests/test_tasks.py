from django.test import TestCase

from travel.models import Destination
from trips.models import Feedback
from trips.tasks import update_traveler_preferences_from_feedback
from users.models import TravelerProfile, User


def _make_destination(slug, *, trip_type, cost_of_living):
    return Destination.objects.create(
        slug=slug,
        name=slug,
        country="Testland",
        latitude=0,
        longitude=0,
        trip_type=trip_type,
        cost_of_living=cost_of_living,
        best_season="Jan-Dec",
        worst_season="None",
        short_description="A test destination.",
        points_of_interest=[],
    )


class UpdateTravelerPreferencesFromFeedbackTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="traveler@example.com", password="testpass123")
        self.culture_a = _make_destination("culture-a", trip_type="culture", cost_of_living=3)
        self.culture_b = _make_destination("culture-b", trip_type="culture", cost_of_living=3)
        self.beach_a = _make_destination("beach-a", trip_type="beach", cost_of_living=1)
        self.beach_b = _make_destination("beach-b", trip_type="beach", cost_of_living=1)

    def test_no_feedback_does_nothing(self):
        update_traveler_preferences_from_feedback(self.user.pk)

        self.assertFalse(TravelerProfile.objects.filter(user=self.user).exists())

    def test_adds_trip_type_after_two_high_ratings(self):
        Feedback.objects.create(user=self.user, destination=self.culture_a, rating=9)
        Feedback.objects.create(user=self.user, destination=self.culture_b, rating=8)

        update_traveler_preferences_from_feedback(self.user.pk)

        profile = TravelerProfile.objects.get(user=self.user)
        self.assertIn("culture", profile.preferred_trip_types)

    def test_does_not_add_trip_type_with_only_one_rating(self):
        Feedback.objects.create(user=self.user, destination=self.culture_a, rating=9)

        update_traveler_preferences_from_feedback(self.user.pk)

        profile = TravelerProfile.objects.get(user=self.user)
        self.assertNotIn("culture", profile.preferred_trip_types)

    def test_does_not_add_trip_type_when_ratings_are_low(self):
        Feedback.objects.create(user=self.user, destination=self.culture_a, rating=3)
        Feedback.objects.create(user=self.user, destination=self.culture_b, rating=4)

        update_traveler_preferences_from_feedback(self.user.pk)

        profile = TravelerProfile.objects.get(user=self.user)
        self.assertNotIn("culture", profile.preferred_trip_types)

    def test_never_removes_an_existing_preferred_trip_type(self):
        TravelerProfile.objects.create(user=self.user, preferred_trip_types=["beach"])
        Feedback.objects.create(user=self.user, destination=self.beach_a, rating=2)
        Feedback.objects.create(user=self.user, destination=self.beach_b, rating=1)

        update_traveler_preferences_from_feedback(self.user.pk)

        profile = TravelerProfile.objects.get(user=self.user)
        self.assertIn("beach", profile.preferred_trip_types)

    def test_sets_cost_of_living_when_unset(self):
        Feedback.objects.create(user=self.user, destination=self.beach_a, rating=9)
        Feedback.objects.create(user=self.user, destination=self.beach_b, rating=8)

        update_traveler_preferences_from_feedback(self.user.pk)

        profile = TravelerProfile.objects.get(user=self.user)
        self.assertEqual(profile.preferred_cost_of_living, 1)

    def test_does_not_override_manually_set_cost_of_living(self):
        TravelerProfile.objects.create(user=self.user, preferred_cost_of_living=5)
        Feedback.objects.create(user=self.user, destination=self.beach_a, rating=9)
        Feedback.objects.create(user=self.user, destination=self.beach_b, rating=8)

        update_traveler_preferences_from_feedback(self.user.pk)

        profile = TravelerProfile.objects.get(user=self.user)
        self.assertEqual(profile.preferred_cost_of_living, 5)

    def test_recompute_is_idempotent(self):
        Feedback.objects.create(user=self.user, destination=self.culture_a, rating=9)
        Feedback.objects.create(user=self.user, destination=self.culture_b, rating=8)

        update_traveler_preferences_from_feedback(self.user.pk)
        first_result = list(TravelerProfile.objects.get(user=self.user).preferred_trip_types)
        update_traveler_preferences_from_feedback(self.user.pk)
        second_result = list(TravelerProfile.objects.get(user=self.user).preferred_trip_types)

        self.assertEqual(first_result, second_result)
        self.assertEqual(TravelerProfile.objects.filter(user=self.user).count(), 1)


class FeedbackSignalTriggersLearningTests(TestCase):
    """Relies on CELERY_TASK_ALWAYS_EAGER=True in test settings, so .delay()
    runs synchronously - no need to mock Celery."""

    def setUp(self):
        self.user = User.objects.create_user(email="traveler@example.com", password="testpass123")
        self.culture_a = _make_destination("culture-a", trip_type="culture", cost_of_living=3)
        self.culture_b = _make_destination("culture-b", trip_type="culture", cost_of_living=3)

    def test_saving_feedback_triggers_preference_learning(self):
        Feedback.objects.create(user=self.user, destination=self.culture_a, rating=9)
        Feedback.objects.create(user=self.user, destination=self.culture_b, rating=9)

        profile = TravelerProfile.objects.get(user=self.user)
        self.assertIn("culture", profile.preferred_trip_types)
