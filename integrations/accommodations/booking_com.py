from datetime import date
from urllib.parse import urlencode

from .base import AccommodationSearchLinkProvider

# The plain, un-tracked search-results URL - validated in production
# (2026-09-23) against CJ Deep Link Automation, which detects and rewrites
# ordinary Booking.com links like this one client-side at click time. Never
# add aid/label/sid or any CJ tracking parameter here - that's the whole
# point of Deep Link Automation over manually built affiliate links, and
# doing it ourselves would just get out of sync with whatever CJ's own
# rewriting actually does.
SEARCH_RESULTS_URL = "https://www.booking.com/searchresults.en-gb.html"


class BookingComSearchLinkProvider(AccommodationSearchLinkProvider):
    def build_search_url(
        self,
        *,
        destination: str,
        country: str = "",
        check_in: date | None = None,
        check_out: date | None = None,
        adults: int | None = None,
        children: int | None = None,
        child_ages: list[int] | None = None,
        rooms: int | None = None,
    ) -> str:
        # "City, Country" is what the validated test searches used (e.g.
        # "Santiago, Chile") - no dest_id/dest_type lookup needed, Booking's
        # own free-text ss param resolves it the same way a visitor typing
        # into the search box would.
        search_term = f"{destination}, {country}" if country else destination
        params = [("ss", search_term)]

        if check_in is not None:
            params.append(("checkin", check_in.isoformat()))
        if check_out is not None:
            params.append(("checkout", check_out.isoformat()))
        if adults is not None:
            params.append(("group_adults", str(adults)))
        if rooms is not None:
            params.append(("no_rooms", str(rooms)))
        if children == 0:
            params.append(("group_children", "0"))
        elif children and child_ages and len(child_ages) == children:
            # One age=N per child (0-17, in order). Children go into the
            # search only together with every age: given a child count and no
            # age, Booking doesn't stop to ask - it quietly reads the child as
            # age 0 and prices the stay for an infant. A count we can't back
            # with ages is left out entirely rather than let Booking invent one.
            params.append(("group_children", str(children)))
            for age in child_ages:
                params.append(("age", str(age)))

        return f"{SEARCH_RESULTS_URL}?{urlencode(params)}"
