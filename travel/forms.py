from django import forms

from .models import CountryEntryRequirement


class CountryEntryRequirementForm(forms.ModelForm):
    class Meta:
        model = CountryEntryRequirement
        fields = [
            "country",
            "visa_required_nationalities",
            "visa_notes",
            "vaccine_requirements",
            "insurance_required",
            "insurance_notes",
            "other_requirements",
        ]


class AddCountryVideoForm(forms.Form):
    url = forms.URLField(label="Video URL", assume_scheme="https")
    language = forms.CharField(label="Language code", max_length=10)
