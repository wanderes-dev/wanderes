from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import views

app_name = "users"

urlpatterns = [
    path("register/", views.register, name="register"),
    path("login/", auth_views.LoginView.as_view(template_name="users/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("account/", views.account, name="account"),
    path("profile/", views.profile, name="profile"),
    # Password reset via emailed token (2026-09-04) - Django's own
    # built-in views/forms/token generator, matching the project's
    # existing "session-based auth is Django's own, no custom
    # reimplementation" convention (07_API_DESIGN.md §3). success_url is
    # explicitly overridden on every view below - these views' own
    # defaults reverse an *unnamespaced* URL name ("password_reset_done"/
    # "password_reset_complete"), which doesn't exist under this app's
    # "users:" namespace and would 404 without the override.
    path(
        "password-reset/",
        auth_views.PasswordResetView.as_view(
            template_name="users/password_reset_form.html",
            email_template_name="users/password_reset_email.txt",
            subject_template_name="users/password_reset_subject.txt",
            success_url=reverse_lazy("users:password_reset_done"),
        ),
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(template_name="users/password_reset_done.html"),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="users/password_reset_confirm.html",
            success_url=reverse_lazy("users:password_reset_complete"),
        ),
        name="password_reset_confirm",
    ),
    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="users/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
]
