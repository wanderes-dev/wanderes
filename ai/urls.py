from django.urls import path

from . import views

app_name = "ai"

urlpatterns = [
    path("chat/", views.chat_page, name="chat"),
    path("api/v1/recommendations/", views.recommendations_stream, name="recommendations-api"),
    path("api/v1/conversations/", views.conversation_list, name="conversation-list"),
    path("api/v1/conversations/reset/", views.conversation_reset, name="conversation-reset"),
    path(
        "api/v1/conversations/<int:pk>/", views.conversation_detail, name="conversation-detail"
    ),
    path(
        "api/v1/conversations/<int:pk>/delete/",
        views.conversation_delete,
        name="conversation-delete",
    ),
]
