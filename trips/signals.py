from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Feedback
from .tasks import update_traveler_preferences_from_feedback


@receiver(post_save, sender=Feedback)
def trigger_preference_learning(sender, instance, **kwargs):
    update_traveler_preferences_from_feedback.delay(instance.user_id)
