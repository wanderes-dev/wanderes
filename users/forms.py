from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.utils.translation import gettext_lazy as _

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
        fields = [
            "preferred_trip_types",
            "preferred_cost_of_living",
            "home_country",
            "travelers_count",
            "budget_amount",
            "budget_period",
        ]
        widgets = {
            "home_country": forms.TextInput(attrs={"placeholder": _("e.g. Brazil")}),
            "travelers_count": forms.NumberInput(attrs={"min": 1}),
            "budget_amount": forms.NumberInput(attrs={"min": 0, "step": "0.01"}),
        }
        labels = {
            "home_country": _("Country of origin"),
            "travelers_count": _("Number of travelers"),
            "budget_amount": _("Budget amount"),
            "budget_period": _("Budget period"),
        }

    def clean(self):
        cleaned_data = super().clean()
        budget_amount = cleaned_data.get("budget_amount")
        budget_period = cleaned_data.get("budget_period")
        if bool(budget_amount) != bool(budget_period):
            raise forms.ValidationError(
                _("Please provide both a budget amount and a budget period, or leave both blank.")
            )
        return cleaned_data
