from django.contrib import admin
from django.urls import include, path

from core.views import set_language

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
    # core.views.set_language (2026-09-04, automatic language detection -
    # was django.conf.urls.i18n's own set_language view directly until
    # this date) - what templates/base.html's language switcher and the
    # language-suggestion banner both POST to. Same URL path and cookie
    # behavior as Django's default view (wraps it rather than replacing
    # it - see core.views.set_language's docstring), plus persisting an
    # authenticated visitor's choice to their account. No URL-prefix
    # i18n_patterns() involved, language is entirely cookie/header/
    # account-based.
    path("i18n/setlang/", set_language, name="set_language"),
]
