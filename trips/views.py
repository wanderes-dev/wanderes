from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .forms import TravelHistoryEntryForm
from .models import TravelHistoryEntry


@login_required
def travel_history_list(request):
    entries = TravelHistoryEntry.objects.filter(user=request.user).select_related("destination")
    return render(request, "trips/travel_history_list.html", {"entries": entries})


@login_required
def travel_history_add(request):
    if request.method == "POST":
        form = TravelHistoryEntryForm(request.POST)
        if form.is_valid():
            entry = form.save(commit=False)
            entry.user = request.user
            entry.save()
            messages.success(request, "Added to your travel history.")
            return redirect("trips:history-list")
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
            messages.success(request, "Updated.")
            return redirect("trips:history-list")
    else:
        form = TravelHistoryEntryForm(instance=entry)
    return render(request, "trips/travel_history_form.html", {"form": form, "is_edit": True})


@login_required
def travel_history_delete(request, pk):
    entry = get_object_or_404(TravelHistoryEntry, pk=pk, user=request.user)
    if request.method == "POST":
        entry.delete()
        messages.success(request, "Removed from your travel history.")
        return redirect("trips:history-list")
    return render(request, "trips/travel_history_confirm_delete.html", {"entry": entry})
