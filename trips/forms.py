from django import forms

from .models import TravelHistoryEntry, Trip


class TravelHistoryEntryForm(forms.ModelForm):
    class Meta:
        model = TravelHistoryEntry
        fields = ["destination", "visited_year"]


class TripForm(forms.ModelForm):
    class Meta:
        model = Trip
        fields = ["name", "destination", "start_date", "end_date", "status"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }
