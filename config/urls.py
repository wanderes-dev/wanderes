from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("admin/", admin.site.urls),
    # The site has no dedicated landing page - send a visitor hitting the
    # bare domain straight to the chat rather than a 404 (surfaced by a
    # real visitor immediately after the first Phase 18 deploy).
    path("", RedirectView.as_view(pattern_name="ai:chat", permanent=False), name="root"),
    path("", include("core.urls")),
    path("users/", include("users.urls")),
    path("", include("ai.urls")),
    path("trips/", include("trips.urls")),
]
