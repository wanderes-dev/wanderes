from django.contrib import messages
from django.contrib.auth import REDIRECT_FIELD_NAME, login
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _

from analytics.models import Event
from analytics.services import record_event

from .forms import TravelerProfileForm, UserRegistrationForm
from .models import TravelerProfile


def _safe_next_url(request):
    """Mirrors django.contrib.auth.views.RedirectURLMixin.get_redirect_url()
    exactly (2026-09-09, contextual account-creation fix) - registration
    previously always landed on users:account, silently dropping a
    ?next= a visitor arrived with (e.g. from trip_create's @login_required
    redirect when saving a recommendation anonymously). Checking POST
    before GET and validating with url_has_allowed_host_and_scheme, same
    as LoginView, avoids both losing a legitimate destination and
    open-redirecting to an attacker-controlled host."""
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
            # Explicit backend required as of 2026-09-03 (Google OAuth
            # login added a second AUTHENTICATION_BACKENDS entry,
            # allauth's own) - login() can no longer guess which backend
            # authenticated this user, since form.save() creates the row
            # directly rather than calling authenticate(). Always
            # ModelBackend here - this is the email/password registration
            # form, never a social signup.
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            record_event("user_registered", user=user)
            next_url = _safe_next_url(request)
            if next_url:
                return HttpResponseRedirect(next_url)
            return redirect("users:account")
    else:
        form = UserRegistrationForm()

    return render(request, "users/register.html", {"form": form})


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
