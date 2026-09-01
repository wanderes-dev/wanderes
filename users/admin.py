from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import TravelerProfile, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    ordering = ["email"]
    list_display = ["email", "is_staff", "is_active"]
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (
            "Permissions",
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),
    )
    search_fields = ["email"]


@admin.register(TravelerProfile)
class TravelerProfileAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "preferred_cost_of_living",
        "home_country",
        "travelers_count",
        "budget_amount",
        "budget_currency",
        "budget_period",
    ]
