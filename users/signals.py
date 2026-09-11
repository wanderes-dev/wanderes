from allauth.account.signals import user_signed_up
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from ai.memory import conversation_key, get_history
from analytics.services import record_event


@receiver(user_signed_up)
def track_social_signup(sender, request, user, **kwargs):
    """Fires the same "user_registered" event as the manual signup path
    (users.views.register), for parity. allauth only sends this signal
    from its own flows, and the manual view never calls into allauth, so
    there's no risk of double-counting a signup."""
    sociallogin = kwargs.get("sociallogin")
    source = sociallogin.account.provider if sociallogin else "email"
    record_event("user_registered", user=user, metadata={"source": source})


@receiver(user_logged_in)
def track_anonymous_conversion(sender, request, user, **kwargs):
    """Records anonymous_user_authenticated - an existing account logging
    in, distinct from user_registered which only fires on registration.

    django.contrib.auth.login() sends user_logged_in unconditionally, so it
    also fires from users.views.register()'s own login() call. The
    `_pre_login_session_key` guard is what excludes registration here: it's
    only set by users.views.LoginView.form_valid, which register() never
    goes through - not just a way to find the right session key.

    Manual login form only for now. A returning Google-OAuth user hits the
    same cycle_key()-before-signal ordering via allauth's pre_social_login
    signal, but wiring that up isn't done - better to skip it than ship a
    path that always reports had_anonymous_conversation=False.
    """
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
