from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import TRIP_TYPE_CHOICES, TravelerProfile, User


class UserRegistrationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("email",)


class TravelerProfileForm(forms.ModelForm):
    preferred_trip_types = forms.MultipleChoiceField(
        choices=TRIP_TYPE_CHOICES, required=False, widget=forms.CheckboxSelectMultiple
    )

    class Meta:
        model = TravelerProfile
        fields = ["preferred_trip_types", "preferred_cost_of_living"]
