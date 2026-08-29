from django.contrib import admin

from .models import Destination


@admin.register(Destination)
class DestinationAdmin(admin.ModelAdmin):
    list_display = ["name", "country", "trip_type", "cost_of_living"]
    list_filter = ["trip_type", "cost_of_living"]
    search_fields = ["name", "country"]
    prepopulated_fields = {"slug": ("name",)}
