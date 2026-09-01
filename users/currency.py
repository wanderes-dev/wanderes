"""Static, approximate USD conversion for TravelerProfile.budget_amount.

2026-09-02, direct user request: "budget must be always on dolar... the
agent must also check for this currency in dolar and convert to estimate".
These are NOT live exchange rates - deliberately a small, static table
rather than a new external provider integration (the user's own framing,
"convert to estimate," matches the same approximate-and-honestly-labeled
approach already used for curated_destinations.json and
country_entry_requirements.json). Real-world rates drift over time, so
treat any conversion this module produces as a rough ballpark, never a
precise or transactional figure - Wanderes performs no currency-based
commerce with this data. It only lets ai.orchestration compare a
traveler's self-reported budget on a common (USD) footing instead of
handing the AI raw numbers in incomparable currencies. Update the rates
below periodically if they visibly drift - this file is the one place to
do it.
"""

from decimal import Decimal

from django.utils.translation import gettext_lazy as _

# Units of each currency per 1 USD (e.g. 1 USD ~= 5.40 BRL) - captured
# 2026-09-02. To convert an amount FROM a currency TO USD, divide by its
# rate here (see convert_to_usd below).
USD_CONVERSION_RATES: dict[str, Decimal] = {
    "USD": Decimal("1"),
    "EUR": Decimal("0.92"),
    "GBP": Decimal("0.79"),
    "BRL": Decimal("5.40"),
    "JPY": Decimal("150"),
    "CNY": Decimal("7.20"),
    "INR": Decimal("83.5"),
    "CAD": Decimal("1.36"),
    "AUD": Decimal("1.52"),
    "CHF": Decimal("0.88"),
    "MXN": Decimal("17.0"),
    "ARS": Decimal("910"),
    "CLP": Decimal("930"),
    "COP": Decimal("3900"),
    "ZAR": Decimal("18.5"),
    "AED": Decimal("3.67"),
    "SGD": Decimal("1.34"),
    "KRW": Decimal("1330"),
    "THB": Decimal("35.0"),
    "SEK": Decimal("10.4"),
    "NOK": Decimal("10.6"),
    "PLN": Decimal("4.00"),
    "TRY": Decimal("32.5"),
    "NZD": Decimal("1.64"),
}

CURRENCY_LABELS: dict[str, str] = {
    "USD": _("US Dollar (USD)"),
    "EUR": _("Euro (EUR)"),
    "GBP": _("British Pound (GBP)"),
    "BRL": _("Brazilian Real (BRL)"),
    "JPY": _("Japanese Yen (JPY)"),
    "CNY": _("Chinese Yuan (CNY)"),
    "INR": _("Indian Rupee (INR)"),
    "CAD": _("Canadian Dollar (CAD)"),
    "AUD": _("Australian Dollar (AUD)"),
    "CHF": _("Swiss Franc (CHF)"),
    "MXN": _("Mexican Peso (MXN)"),
    "ARS": _("Argentine Peso (ARS)"),
    "CLP": _("Chilean Peso (CLP)"),
    "COP": _("Colombian Peso (COP)"),
    "ZAR": _("South African Rand (ZAR)"),
    "AED": _("UAE Dirham (AED)"),
    "SGD": _("Singapore Dollar (SGD)"),
    "KRW": _("South Korean Won (KRW)"),
    "THB": _("Thai Baht (THB)"),
    "SEK": _("Swedish Krona (SEK)"),
    "NOK": _("Norwegian Krone (NOK)"),
    "PLN": _("Polish Zloty (PLN)"),
    "TRY": _("Turkish Lira (TRY)"),
    "NZD": _("New Zealand Dollar (NZD)"),
}

# USD first (the most common default), then the rest alphabetically by code.
CURRENCY_CHOICES = [("USD", CURRENCY_LABELS["USD"])] + [
    (code, CURRENCY_LABELS[code]) for code in sorted(CURRENCY_LABELS) if code != "USD"
]


def convert_to_usd(amount, currency_code: str):
    """Convert `amount` in `currency_code` to an approximate USD amount.

    Returns None (never raises) if the amount is missing or the currency
    isn't in our static table - callers must treat that as "couldn't
    estimate," not as a zero budget.
    """
    if amount is None or not currency_code:
        return None
    rate = USD_CONVERSION_RATES.get(currency_code)
    if not rate:
        return None
    return amount / rate
