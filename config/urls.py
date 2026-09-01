from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    # core.urls owns the bare domain root - a real landing page (2026-09-01),
    # not a redirect straight into /chat/ (the previous behavior, added
    # right after the first Phase 18 deploy just to avoid a 404).
    path("", include("core.urls")),
    path("users/", include("users.urls")),
    path("", include("ai.urls")),
    path("trips/", include("trips.urls")),
]
