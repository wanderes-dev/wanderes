from django.urls import path

from . import views

app_name = "trips"

urlpatterns = [
    path("history/add/", views.travel_history_add, name="history-add"),
    path("history/<int:pk>/edit/", views.travel_history_edit, name="history-edit"),
    path("history/<int:pk>/delete/", views.travel_history_delete, name="history-delete"),
    path("", views.trip_list, name="trip-list"),
    path("create/", views.trip_create, name="trip-create"),
    path("<int:pk>/", views.trip_detail, name="trip-detail"),
    path("<int:pk>/edit/", views.trip_edit, name="trip-edit"),
    path("<int:pk>/delete/", views.trip_delete, name="trip-delete"),
    path("<int:pk>/feedback/", views.trip_feedback, name="trip-feedback"),
]
