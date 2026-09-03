from allauth.account.signals import user_signed_up
from django.dispatch import receiver

from analytics.services import record_event


@receiver(user_signed_up)
def track_social_signup(sender, request, user, **kwargs):
    """Records the same "user_registered" analytics event the manual
    email/password path already fires (users.views.register), for parity
    (2026-09-03, Google OAuth login). allauth only ever sends this signal
    from its own signup flows - the manual registration view never calls
    into allauth at all - so there is no risk of double-counting one
    signup as two events."""
    sociallogin = kwargs.get("sociallogin")
    source = sociallogin.account.provider if sociallogin else "email"
    record_event("user_registered", user=user, metadata={"source": source})
