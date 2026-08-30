from django.contrib import admin

from .models import Event


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("event_type", "user", "anonymized_ip", "created_at")
    list_filter = ("event_type",)
    date_hierarchy = "created_at"
    search_fields = ("user__email", "anonymized_ip")
    readonly_fields = ("event_type", "user", "anonymized_ip", "metadata", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
