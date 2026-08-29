from django.urls import path

from . import views

app_name = "ai"

urlpatterns = [
    path("chat/", views.chat_page, name="chat"),
    path("api/v1/recommendations/", views.recommendations_stream, name="recommendations-api"),
]
