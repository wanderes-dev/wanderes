from django.contrib import admin

from .models import Feedback, Trip, TripAccommodation, TripFlight


class TripFlightInline(admin.TabularInline):
    model = TripFlight
    extra = 0


class TripAccommodationInline(admin.TabularInline):
    model = TripAccommodation
    extra = 0


@admin.register(Trip)
class TripAdmin(admin.ModelAdmin):
    list_display = ["user", "destination", "status", "start_date", "end_date"]
    list_filter = ["status"]
    inlines = [TripFlightInline, TripAccommodationInline]


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ["user", "destination", "trip", "rating", "created_at"]
    list_filter = ["rating"]
