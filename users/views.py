from django.contrib import messages
from django.contrib.auth import REDIRECT_FIELD_NAME, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView as _LoginView
from django.http import HttpResponseRedirect
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _

from analytics.models import Event
from analytics.services import record_event

from .forms import TravelerProfileForm, UserRegistrationForm
from .models import TravelerProfile


def _safe_next_url(request):
    """Mirrors django.contrib.auth.views.RedirectURLMixin.get_redirect_url().

    Without this, registration always landed on users:account and silently
    dropped a ?next= the visitor arrived with (e.g. from trip_create's
    @login_required redirect). Checks POST before GET and validates with
    url_has_allowed_host_and_scheme, same as LoginView - don't drop this
    check, it's what stops an open redirect to an attacker-controlled host.
    """
    next_url = request.POST.get(REDIRECT_FIELD_NAME) or request.GET.get(REDIRECT_FIELD_NAME)
    if next_url and url_has_allowed_host_and_scheme(
        url=next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    return None


def register(request):
    if request.user.is_authenticated:
        return redirect("users:account")

    if request.method == "POST":
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            # Backend has to be explicit now that AUTHENTICATION_BACKENDS
            # has a second entry (allauth's, for Google login) - login()
            # can't infer which backend authenticated this user since
            # form.save() creates the row directly, no authenticate() call.
            # Always ModelBackend here, this form is email/password only.
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            record_event("user_registered", user=user)
            next_url = _safe_next_url(request)
            if next_url:
                return HttpResponseRedirect(next_url)
            return redirect("users:account")
    else:
        form = UserRegistrationForm()
        # Pairs with user_registered to give a signup funnel. Directional,
        # not exact - a page refresh fires this again, same as any
        # funnel-entry pageview signal.
        record_event("signup_started", user=None, request=request)

    return render(request, "users/register.html", {"form": form})


class LoginView(_LoginView):
    """Wraps Django's LoginView to stash the pre-login session key.

    Django's login() rotates the session key via cycle_key() as part of
    form_valid() - by the time user_logged_in fires, session.session_key
    already points at the *new* session, so a receiver reading it directly
    would look up an anonymous conversation under a key that was never
    written to. Stashing the real key here is the only way
    users.signals.track_anonymous_conversion can tell whether this visitor
    had an anonymous chat going. Otherwise unchanged - just adds one
    attribute before delegating to the real form_valid().
    """

    def form_valid(self, form):
        self.request._pre_login_session_key = self.request.session.session_key
        return super().form_valid(form)


@login_required
def account(request):
    return render(request, "users/account.html", {"user": request.user})


@login_required
def profile(request):
    # Always operates on request.user's own profile - never accepts a
    # profile id from the URL, so there is no cross-user access to guard
    # against by construction.
    traveler_profile, _created = TravelerProfile.objects.get_or_create(user=request.user)

    if request.method == "POST":
        form = TravelerProfileForm(request.POST, instance=traveler_profile)
        if form.is_valid():
            profile = form.save()
            is_now_complete = bool(
                profile.preferred_trip_types
                or profile.preferred_cost_of_living is not None
                or profile.home_country
                or profile.travelers_count is not None
                or profile.budget_amount is not None
            )
            if is_now_complete and not Event.objects.filter(
                user=request.user, event_type="profile_completed"
            ).exists():
                # Fired once, the first time the profile has real content -
                # not on every subsequent edit.
                record_event("profile_completed", user=request.user)
            messages.success(request, _("Your traveler profile was updated."))
            return redirect("users:profile")
    else:
        form = TravelerProfileForm(instance=traveler_profile)

    return render(request, "users/profile.html", {"form": form})
