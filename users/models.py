from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _

# Same 1-5 scale used by travel.Destination.cost_of_living, so a traveler's
# preferred cost of living and a destination's cost of living are directly
# comparable - imported from travel.models (the canonical source, since it
# owns the destination catalog these choices describe) rather than
# duplicated here. A 2026-09-02 review found this file had its own
# byte-for-byte copy of both lists, independent of travel.models' and of
# ai.orchestration's INTENT_SCHEMA enum - nothing kept the three in sync,
# so changing a trip type in one place risked silently desyncing the
# others. Re-exported under these same names so existing imports
# (users/forms.py's `from .models import TRIP_TYPE_CHOICES`) don't need to
# change.
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

    Login is by email (not username) per the 2026-08-29 product decision.
    Google OAuth is a planned future login method (not yet implemented) —
    this model doesn't need extra fields for that; it would be handled by
    a social-auth library (e.g. django-allauth) linking to this model.
    """

    username = None
    email = models.EmailField("email address", unique=True)

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

    Originally deliberately thin per 14_MVP_IMPLEMENTATION_PLAN.md
    Milestone 2 ("do not build the complete traveler profile yet").
    Extended 2026-09-02 (direct user request) with home_country,
    travelers_count, and a budget amount/period/currency triple - concrete
    trip-context fields, distinct from preferred_cost_of_living's abstract
    1-5 tier. budget_amount/budget_period/budget_currency are validated
    (TravelerProfileForm.clean()) to always be filled in together or not
    at all - a bare number with no currency or time unit is meaningless.
    budget_currency exists specifically so ai.orchestration can convert a
    self-reported budget to an approximate USD figure (users.currency,
    same-day follow-up request: "budget must be always on dolar") instead
    of comparing raw numbers in incomparable currencies. Preference
    history, inferred preferences, and feedback-driven learning belong to
    later milestones.
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
