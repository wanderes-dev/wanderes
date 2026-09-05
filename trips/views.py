from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from analytics.services import record_event
from travel.models import Destination

from .forms import FeedbackForm, TravelHistoryEntryForm, TripForm
from .models import FEEDBACK_TAG_CHOICES, Feedback, TravelHistoryEntry, Trip

FEEDBACK_TAG_LABELS = dict(FEEDBACK_TAG_CHOICES)


@login_required
def travel_history_add(request):
    if request.method == "POST":
        form = TravelHistoryEntryForm(request.POST)
        if form.is_valid():
            entry = form.save(commit=False)
            entry.user = request.user
            entry.save()
            messages.success(request, _("Added to your travel history."))
            return redirect("trips:trip-list")
    else:
        form = TravelHistoryEntryForm()
    return render(request, "trips/travel_history_form.html", {"form": form, "is_edit": False})


@login_required
def travel_history_edit(request, pk):
    # Structural authorization: only ever fetches the caller's own entry.
    entry = get_object_or_404(TravelHistoryEntry, pk=pk, user=request.user)
    if request.method == "POST":
        form = TravelHistoryEntryForm(request.POST, instance=entry)
        if form.is_valid():
            form.save()
            messages.success(request, _("Updated."))
            return redirect("trips:trip-list")
    else:
        form = TravelHistoryEntryForm(instance=entry)
    return render(request, "trips/travel_history_form.html", {"form": form, "is_edit": True})


@login_required
def travel_history_delete(request, pk):
    entry = get_object_or_404(TravelHistoryEntry, pk=pk, user=request.user)
    if request.method == "POST":
        entry.delete()
        messages.success(request, _("Removed from your travel history."))
        return redirect("trips:trip-list")
    return render(request, "trips/travel_history_confirm_delete.html", {"entry": entry})


@login_required
def trip_list(request):
    # 2026-09-05, direct request: "desfaça a aba my history, quero que o
    # historico seja possivel consultar dentro de my trips" - travel
    # history is no longer its own top-level nav destination
    # (trips:history-list removed); it's shown as a second section on
    # this same page instead. TravelHistoryEntry stays its own model/URLs
    # (add/edit/delete) - only the standalone list page and nav entry are
    # gone.
    trips = Trip.objects.filter(user=request.user).select_related("destination")
    history_entries = TravelHistoryEntry.objects.filter(user=request.user).select_related(
        "destination"
    )
    return render(
        request, "trips/trip_list.html", {"trips": trips, "history_entries": history_entries}
    )


@login_required
def trip_create(request):
    # Supports "save this recommendation as a trip" from the chat page,
    # which links here with ?destination=<slug> pre-filled.
    initial = {}
    destination_slug = request.GET.get("destination")
    if destination_slug:
        destination = Destination.objects.filter(slug=destination_slug).first()
        if destination:
            initial["destination"] = destination.pk

    if request.method == "POST":
        form = TripForm(request.POST)
        if form.is_valid():
            trip = form.save(commit=False)
            trip.user = request.user
            trip.save()
            record_event(
                "trip_created",
                user=request.user,
                metadata={
                    "destination_slug": trip.destination.slug,
                    "status": trip.status,
                    "source": "form",
                },
            )
            messages.success(request, _("Trip saved."))
            return redirect("trips:trip-detail", pk=trip.pk)
    else:
        form = TripForm(initial=initial)
    return render(request, "trips/trip_form.html", {"form": form, "is_edit": False})


@login_required
def trip_detail(request, pk):
    trip = get_object_or_404(Trip, pk=pk, user=request.user)
    feedback = Feedback.objects.filter(trip=trip, user=request.user).first()
    feedback_tag_labels = (
        [FEEDBACK_TAG_LABELS.get(tag, tag) for tag in feedback.tags] if feedback else []
    )
    return render(
        request,
        "trips/trip_detail.html",
        {"trip": trip, "feedback": feedback, "feedback_tag_labels": feedback_tag_labels},
    )


@login_required
def trip_edit(request, pk):
    trip = get_object_or_404(Trip, pk=pk, user=request.user)
    if request.method == "POST":
        form = TripForm(request.POST, instance=trip)
        if form.is_valid():
            form.save()
            messages.success(request, _("Trip updated."))
            return redirect("trips:trip-detail", pk=trip.pk)
    else:
        form = TripForm(instance=trip)
    return render(request, "trips/trip_form.html", {"form": form, "is_edit": True})


@login_required
def trip_delete(request, pk):
    trip = get_object_or_404(Trip, pk=pk, user=request.user)
    if request.method == "POST":
        trip.delete()
        messages.success(request, _("Trip deleted."))
        return redirect("trips:trip-list")
    return render(request, "trips/trip_confirm_delete.html", {"trip": trip})


@login_required
def trip_feedback(request, pk):
    # One feedback entry per (user, trip): re-submitting edits the
    # existing entry rather than creating a duplicate.
    trip = get_object_or_404(Trip, pk=pk, user=request.user)
    instance = Feedback.objects.filter(trip=trip, user=request.user).first()

    if request.method == "POST":
        form = FeedbackForm(request.POST, instance=instance)
        if form.is_valid():
            feedback = form.save(commit=False)
            feedback.user = request.user
            feedback.trip = trip
            feedback.destination = trip.destination
            feedback.save()
            record_event(
                "feedback_submitted",
                user=request.user,
                metadata={
                    "destination_slug": trip.destination.slug,
                    "rating": feedback.rating,
                    "source": "form",
                },
            )
            messages.success(request, _("Thanks for your feedback!"))
            return redirect("trips:trip-detail", pk=trip.pk)
    else:
        form = FeedbackForm(instance=instance)
    return render(request, "trips/trip_feedback_form.html", {"form": form, "trip": trip})
