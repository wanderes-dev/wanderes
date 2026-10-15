from django.urls import path

from . import views

app_name = "dietmed"

urlpatterns = [
    path("", views.redirect_to_partner, name="redirect"),
]
