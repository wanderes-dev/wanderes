from django import forms

from .models import FEEDBACK_TAG_CHOICES, Feedback, TravelHistoryEntry, Trip


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


class FeedbackForm(forms.ModelForm):
    tags = forms.MultipleChoiceField(
        choices=FEEDBACK_TAG_CHOICES, required=False, widget=forms.CheckboxSelectMultiple
    )

    class Meta:
        model = Feedback
        fields = ["rating", "tags", "comment"]
