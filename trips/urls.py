from django.urls import path

from . import views

app_name = "trips"

urlpatterns = [
    path("history/", views.travel_history_list, name="history-list"),
    path("history/add/", views.travel_history_add, name="history-add"),
    path("history/<int:pk>/edit/", views.travel_history_edit, name="history-edit"),
    path("history/<int:pk>/delete/", views.travel_history_delete, name="history-delete"),
]
