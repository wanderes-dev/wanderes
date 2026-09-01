from django.contrib import admin

from .models import CountryEntryRequirement, Destination


@admin.register(Destination)
class DestinationAdmin(admin.ModelAdmin):
    list_display = ["name", "country", "trip_type", "cost_of_living"]
    list_filter = ["trip_type", "cost_of_living"]
    search_fields = ["name", "country"]
    prepopulated_fields = {"slug": ("name",)}


@admin.register(CountryEntryRequirement)
class CountryEntryRequirementAdmin(admin.ModelAdmin):
    list_display = ["country", "insurance_required", "updated_at"]
    search_fields = ["country"]
