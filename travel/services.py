from django.db.models import Q

from .models import Destination


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
