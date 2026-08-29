from django import forms

from .models import TravelHistoryEntry


class TravelHistoryEntryForm(forms.ModelForm):
    class Meta:
        model = TravelHistoryEntry
        fields = ["destination", "visited_year"]
