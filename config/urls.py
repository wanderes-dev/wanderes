from django.contrib import admin
from django.urls import include, path

from core.views import set_language

urlpatterns = [
    path("admin/", admin.site.urls),
    # core.urls owns the bare domain root - a real landing page, not a
    # redirect straight into /chat/ (that was the original behavior,
    # added right after the first deploy just to avoid a 404).
    path("", include("core.urls")),
    path("users/", include("users.urls")),
    path("", include("ai.urls")),
    path("trips/", include("trips.urls")),
    # Staff-only country editing tools - not linked from the public nav,
    # same as /admin/ itself isn't.
    path("travel/", include("travel.urls")),
    # Staff-only internal analytics dashboard - same not-linked-from-nav
    # pattern as travel.urls above.
    path("analytics/", include("analytics.urls")),
    # django-allauth (Google OAuth login) - additive to users.urls's
    # existing email/password login/register, never a replacement. Only
    # the Google provider is actually configured (see
    # SOCIALACCOUNT_PROVIDERS in settings/base.py); allauth's own generic
    # account-management URLs (password reset, email management, etc.)
    # come along with this include but aren't linked from anywhere in the
    # UI - users.urls's own forms still own that.
    path("accounts/", include("allauth.urls")),
    # core.views.set_language - what templates/base.html's language
    # switcher and the language-suggestion banner both POST to. Same URL
    # path and cookie behavior as Django's default view (wraps it rather
    # than replacing it - see core.views.set_language's docstring), plus
    # persisting an authenticated visitor's choice to their account. No
    # URL-prefix i18n_patterns() involved - language is entirely
    # cookie/header/account-based.
    path("i18n/setlang/", set_language, name="set_language"),
]
