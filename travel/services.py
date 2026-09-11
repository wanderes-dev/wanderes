from django.db.models import Q

from .models import CountryEntryRequirement, Destination

# Must accompany CountryEntryRequirement data wherever it's shown or
# referenced (see that model's docstring) - visa/vaccine/insurance info
# is compiled from general knowledge, not verified against an official
# source, and getting it wrong has real consequences (denied boarding or
# entry) unlike a merely inaccurate destination fact.
ENTRY_REQUIREMENT_DISCLAIMER = (
    "This is general guidance only, not verified against official sources, "
    "and does not cover every country. Requirements change and can depend "
    "on your specific nationality, passport, trip purpose, and length of "
    "stay - always confirm with the destination country's official "
    "government or embassy website and your airline before booking or "
    "traveling."
)


def get_entry_requirements(country_name: str) -> CountryEntryRequirement | None:
    """Look up entry-requirement guidance for a country by name
    (case-insensitive). Returns None if nothing's on file - callers
    shouldn't read that as "no requirements exist", just "we don't have
    data for this one" (see ENTRY_REQUIREMENT_DISCLAIMER)."""
    if not country_name:
        return None
    return CountryEntryRequirement.objects.filter(country__iexact=country_name.strip()).first()


def resolve_country_name(place_name: str) -> str | None:
    """Best-effort resolution of a free-text place name to a country
    name, for looking up CountryEntryRequirement.videos. A traveler
    might name a city ("Lisbon") or already a country ("Portugal") - try
    matching a Destination by name or country first and return its real
    .country, falling back to the raw input if nothing matches. Callers
    can still run that through get_entry_requirements's own lookup,
    which returns None gracefully instead of guessing."""
    if not place_name:
        return None
    place_name = place_name.strip()
    if not place_name:
        return None
    destination = Destination.objects.filter(
        Q(name__icontains=place_name) | Q(country__icontains=place_name)
    ).first()
    return destination.country if destination else place_name


def find_destination_slugs_by_name(place_names: list[str]) -> frozenset:
    """Resolve free-text place/country names to matching Destination slugs.

    Used to turn a traveler's exclusion request ("not Marrakech or
    Morocco") into slugs recommendations.scoring can filter on.
    Case-insensitive substring match against name/country - good enough
    for the current dataset size; a much bigger catalog would need
    something more precise.
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
