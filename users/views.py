from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from analytics.models import Event
from analytics.services import record_event

from .forms import TravelerProfileForm, UserRegistrationForm
from .models import TravelerProfile


def register(request):
    if request.user.is_authenticated:
        return redirect("users:account")

    if request.method == "POST":
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            record_event("user_registered", user=user)
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
    traveler_profile, _ = TravelerProfile.objects.get_or_create(user=request.user)

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
            messages.success(request, "Your traveler profile was updated.")
            return redirect("users:profile")
    else:
        form = TravelerProfileForm(instance=traveler_profile)

    return render(request, "users/profile.html", {"form": form})
