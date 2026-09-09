from allauth.account.signals import user_signed_up
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from ai.memory import conversation_key, get_history
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


@receiver(user_logged_in)
def track_anonymous_conversion(sender, request, user, **kwargs):
    """Records anonymous_user_authenticated (2026-09-09) - a chat visitor
    logging into an EXISTING account, distinct from user_registered (which
    only fires on registration).

    django.contrib.auth.login() sends user_logged_in unconditionally,
    including from users.views.register()'s own call to it - the
    `_pre_login_session_key` guard below is what keeps this from also
    firing on every registration (it's only ever set by
    users.views.LoginView.form_valid, which register() doesn't go
    through), not just a mechanism for reading the right session key.

    Manual login form only this pass: a returning Google-OAuth user hits
    the identical cycle_key()-before-signal ordering via allauth's own
    pre_social_login signal, which this pass deliberately does not wire up
    - shipping a path that would silently always record
    had_anonymous_conversation=False would be worse than not building it.
    Same "add it when it's real" precedent already used for
    premium_started/affiliate_link_clicked."""
    if not hasattr(request, "_pre_login_session_key"):
        return

    had_anonymous_conversation = False
    pre_login_session_key = request._pre_login_session_key
    if pre_login_session_key:
        key = conversation_key(user=None, session_key=pre_login_session_key)
        had_anonymous_conversation = bool(get_history(key))

    record_event(
        "anonymous_user_authenticated",
        user=user,
        metadata={"had_anonymous_conversation": had_anonymous_conversation},
    )
