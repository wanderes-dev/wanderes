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
    # django-allauth (2026-09-03, Google OAuth login) - additive to
    # users.urls's existing email/password login/register, never a
    # replacement. Only the Google provider is actually configured (see
    # SOCIALACCOUNT_PROVIDERS in settings/base.py); allauth's own generic
    # account-management URLs (password reset, email management, etc.)
    # come along with this include but aren't linked from anywhere in the
    # UI - users.urls's own forms still own that.
    path("accounts/", include("allauth.urls")),
    # django.conf.urls.i18n's set_language view (2026-09-04, translation
    # rollout) - what templates/base.html's language switcher POSTs to.
    # Sets a cookie and redirects back to the "next" page; no URL-prefix
    # i18n_patterns() involved, language is entirely cookie/header-based.
    path("i18n/", include("django.conf.urls.i18n")),
]
