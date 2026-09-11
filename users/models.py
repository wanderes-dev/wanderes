from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _

# Pulled from travel.models rather than duplicated here, so this file's
# cost-of-living scale always matches travel.Destination.cost_of_living
# (used to be its own copy, which drifted out of sync with both
# travel.models and ai.orchestration's intent schema). Re-exported under
# the same names so users/forms.py's `from .models import TRIP_TYPE_CHOICES`
# doesn't need to change.
from travel.models import COST_OF_LIVING_CHOICES, TRIP_TYPE_CHOICES  # noqa: F401

from .currency import CURRENCY_CHOICES


class UserManager(DjangoUserManager):
    """Creates users by email instead of Django's default username field."""

    def _create_user(self, email=None, password=None, **extra_fields):
        if not email:
            raise ValueError("Users must have an email address")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email=None, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email=None, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    """Wanderes account and authentication identity.

    Login is by email, not username. Google OAuth is a planned login
    method - this model doesn't need extra fields for it, a social-auth
    library (e.g. django-allauth) would just link to this model.
    """

    username = None
    email = models.EmailField("email address", unique=True)

    # An explicit choice made while logged in, so it follows the account
    # across devices instead of living only in the anonymous per-browser
    # django_language cookie LocaleMiddleware reads. Blank = no explicit
    # choice yet, cookie/Accept-Language detection applies as normal (see
    # core.middleware.UserLanguagePreferenceMiddleware, which prefers this
    # over the cookie/header once it's set).
    preferred_language = models.CharField(
        max_length=10,
        choices=settings.LANGUAGES,
        blank=True,
        help_text=_("Explicit UI language choice, applied on every device once set."),
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    def __str__(self):
        return self.email


BUDGET_PERIOD_CHOICES = [
    ("day", _("Per day")),
    ("week", _("Per week")),
    ("month", _("Per month")),
]


class TravelerProfile(models.Model):
    """Traveler preferences used to personalize recommendations.

    Kept deliberately thin - no preference history, inferred preferences,
    or feedback-driven learning yet, that's for later. home_country,
    travelers_count and the budget amount/period/currency triple are
    concrete trip-context fields, distinct from preferred_cost_of_living's
    abstract 1-5 tier. budget_amount/budget_period/budget_currency are
    validated together in TravelerProfileForm.clean() - a bare number with
    no currency or time unit isn't meaningful on its own. budget_currency
    is also what lets ai.orchestration convert a self-reported budget to an
    approximate USD figure (see users.currency) instead of comparing raw
    numbers across incomparable currencies.
    """

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="traveler_profile")
    preferred_trip_types = models.JSONField(
        default=list,
        blank=True,
        help_text=_("List of preferred trip type codes, e.g. ['beach', 'culture']."),
    )
    preferred_cost_of_living = models.PositiveSmallIntegerField(
        choices=COST_OF_LIVING_CHOICES, null=True, blank=True
    )
    home_country = models.CharField(
        max_length=200,
        blank=True,
        help_text=_("Where you usually travel from, e.g. 'Brazil'."),
    )
    travelers_count = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text=_("How many people you usually travel with, including yourself."),
    )
    budget_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_("Typical travel budget, paired with budget_period."),
    )
    budget_period = models.CharField(
        max_length=10, choices=BUDGET_PERIOD_CHOICES, blank=True
    )
    budget_currency = models.CharField(
        max_length=3,
        choices=CURRENCY_CHOICES,
        blank=True,
        help_text=_("The currency budget_amount is stated in - required alongside it."),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Traveler profile for {self.user.email}"
