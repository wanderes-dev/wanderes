from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import views

app_name = "users"

urlpatterns = [
    path("register/", views.register, name="register"),
    # views.LoginView, not auth_views.LoginView directly - see its
    # docstring, it captures the pre-login session key before login()
    # rotates it, needed for the anonymous_user_authenticated event.
    path("login/", views.LoginView.as_view(template_name="users/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("account/", views.account, name="account"),
    path("profile/", views.profile, name="profile"),
    # Password reset via emailed token - Django's own built-in views/
    # forms/token generator (07_API_DESIGN.md §3: no custom auth
    # reimplementation). success_url is overridden on every view below
    # because their defaults reverse an unnamespaced URL name
    # ("password_reset_done" etc), which 404s under our "users:" namespace.
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
