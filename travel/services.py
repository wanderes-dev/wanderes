from django.db.models import Q

from .models import CountryEntryRequirement, Destination

# Must accompany CountryEntryRequirement data wherever it's ever shown or
# referenced (see that model's docstring) - visa/vaccine/insurance
# requirements are compiled from general knowledge, not verified against
# each country's official source, change over time, and getting them
# wrong carries real consequences (denied boarding/entry, a real
# health/legal problem) unlike a merely inaccurate destination fact.
ENTRY_REQUIREMENT_DISCLAIMER = (
    "This is general guidance only, not verified against official sources, "
    "and does not cover every country. Requirements change and can depend "
    "on your specific nationality, passport, trip purpose, and length of "
    "stay - always confirm with the destination country's official "
    "government or embassy website and your airline before booking or "
    "traveling."
)


def get_entry_requirements(country_name: str) -> CountryEntryRequirement | None:
    """Look up entry-requirement guidance for a destination country by
    name (case-insensitive). Returns None if nothing is on file for it -
    callers must not treat that as "no requirements exist", only as "we
    don't have data for this one" (see ENTRY_REQUIREMENT_DISCLAIMER)."""
    if not country_name:
        return None
    return CountryEntryRequirement.objects.filter(country__iexact=country_name.strip()).first()


def find_destination_slugs_by_name(place_names: list[str]) -> frozenset:
    """Resolve free-text place/country names to matching Destination slugs.

    Used to translate a traveler's exclusion request ("not Marrakech or
    Morocco") into slugs recommendations.scoring can filter on. Matching is
    case-insensitive substring matching against name/country - simple and
    good enough for the curated dataset's size; a much larger catalog would
    need a more precise search strategy.
    """
    if not place_names:
        return frozenset()

    query = Q()
    has_terms = False
    for term in place_names:
        term = term.strip()
        if not term:
            continue
        query |= Q(name__icontains=term) | Q(country__icontains=term)
        has_terms = True

    if not has_terms:
        return frozenset()

    return frozenset(Destination.objects.filter(query).values_list("slug", flat=True))
