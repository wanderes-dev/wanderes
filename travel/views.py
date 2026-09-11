from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from .forms import AddCountryVideoForm, CountryEntryRequirementForm
from .models import CountryEntryRequirement

# Staff-only country editing tools. Gated with Django's own
# staff_member_required (matches User.is_staff on the custom user model)
# rather than a new permission concept - not linked from the public nav,
# same as /admin/ itself.


@staff_member_required
def country_admin_list(request):
    countries = CountryEntryRequirement.objects.order_by("country")
    return render(request, "travel/country_admin_list.html", {"countries": countries})


@staff_member_required
def country_admin_create(request):
    if request.method == "POST":
        form = CountryEntryRequirementForm(request.POST)
        if form.is_valid():
            country = form.save()
            messages.success(request, _("Country created."))
            return redirect("travel:country-edit", pk=country.pk)
    else:
        form = CountryEntryRequirementForm()
    return render(request, "travel/country_admin_form.html", {"form": form, "is_edit": False})


@staff_member_required
def country_admin_edit(request, pk):
    country = get_object_or_404(CountryEntryRequirement, pk=pk)
    if request.method == "POST":
        form = CountryEntryRequirementForm(request.POST, instance=country)
        if form.is_valid():
            form.save()
            messages.success(request, _("Country updated."))
            return redirect("travel:country-edit", pk=country.pk)
    else:
        form = CountryEntryRequirementForm(instance=country)
    return render(
        request,
        "travel/country_admin_form.html",
        {
            "form": form,
            "is_edit": True,
            "country": country,
            "add_video_form": AddCountryVideoForm(),
        },
    )


@staff_member_required
def country_admin_add_video(request, pk):
    country = get_object_or_404(CountryEntryRequirement, pk=pk)
    if request.method == "POST":
        form = AddCountryVideoForm(request.POST)
        if form.is_valid():
            country.videos.append(
                [form.cleaned_data["url"], form.cleaned_data["language"].upper()]
            )
            country.save(update_fields=["videos"])
            messages.success(request, _("Video added."))
    return redirect("travel:country-edit", pk=country.pk)


@staff_member_required
def country_admin_remove_video(request, pk, index):
    country = get_object_or_404(CountryEntryRequirement, pk=pk)
    if request.method == "POST" and 0 <= index < len(country.videos):
        country.videos.pop(index)
        country.save(update_fields=["videos"])
        messages.success(request, _("Video removed."))
    return redirect("travel:country-edit", pk=country.pk)
