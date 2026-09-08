from django.urls import path

from . import views

app_name = "travel"

urlpatterns = [
    path("admin-tools/countries/", views.country_admin_list, name="country-list"),
    path("admin-tools/countries/new/", views.country_admin_create, name="country-create"),
    path("admin-tools/countries/<int:pk>/", views.country_admin_edit, name="country-edit"),
    path(
        "admin-tools/countries/<int:pk>/videos/add/",
        views.country_admin_add_video,
        name="country-add-video",
    ),
    path(
        "admin-tools/countries/<int:pk>/videos/<int:index>/remove/",
        views.country_admin_remove_video,
        name="country-remove-video",
    ),
]
