"""Continent classification for Destination.country values (2026-09-04,
real production bug: a "Eurotrip" request's recommendation cards
included Bali, Marrakech, Chiang Mai, Hoi An, and Ayutthaya alongside the
genuinely European options - the deterministic scoring pipeline had no
way to filter by continent at all, only country/trip_type/budget/
temperature, so "Europe" as a hard constraint had nowhere to go).

Destination.country stores a specific country name (in English, matching
the curated dataset's canonical language since the 2026-09-08 dataset
translation - see DEVELOPMENT_LOG.md for why the dataset moved from
Portuguese to English) - there is no continent field on the model, and
none is added here either; a schema change/migration isn't needed for a
lookup this small and static.
COUNTRIES_BY_CONTINENT below is a plain, hand-maintained mapping,
classified using the UN M49 macro-region standard
(https://unstats.un.org/unsd/methodology/m49/) for consistency, rather
than ad hoc personal judgment calls - consolidated from the UN's finer
sub-regions (e.g. "Eastern Europe", "Western Asia") down to the 6
continents travelers actually name in conversation.

A handful of transcontinental countries are worth calling out
explicitly rather than leaving as a silent judgment call: Russia is
classified as Europe (UN M49 groups it under Eastern Europe); Turkey,
Georgia, Armenia, Azerbaijan, and Cyprus are classified as Asia (UN M49
groups all five under Western Asia) - despite Cyprus's and Turkey's
partial cultural/political European ties (EU membership for Cyprus, EU
candidate status for Turkey), this keeps one single, consistent, citable
standard rather than picking and choosing per country.

`travel/tests/test_geography.py`'s test_every_curated_country_is_classified
guards against a future catalog addition silently falling outside every
continent (an unclassified country simply never matches any continent
filter, degrading silently to "no results" instead of erroring) - expect
to need an update here whenever travel/data/curated_destinations.json
introduces a country not seen before.
"""

EUROPE = frozenset(
    {
        "Albania",
        "Germany",
        "Andorra",
        "Belgium",
        "Bosnia and Herzegovina",
        "Croatia",
        "Denmark",
        "Slovakia",
        "Slovenia",
        "Spain",
        "Estonia",
        "Finland",
        "France",
        "Greece",
        "Hungary",
        "Faroe Islands",
        "Ireland",
        "Iceland",
        "Italy",
        "Latvia",
        "Lithuania",
        "Luxembourg",
        "Malta",
        "Montenegro",
        "Monaco",
        "Norway",
        "Netherlands",
        "Poland",
        "Portugal",
        "United Kingdom",
        "Czech Republic",
        "Romania",
        "Russia",
        "Sweden",
        "Switzerland",
        "Serbia",
        "Austria",
    }
)

ASIA = frozenset(
    {
        "Armenia",
        "Saudi Arabia",
        "Azerbaijan",
        "Bahrain",
        "Bhutan",
        "Cambodia",
        "Qatar",
        "Kazakhstan",
        "China",
        "Cyprus",
        "South Korea",
        "United Arab Emirates",
        "Philippines",
        "Georgia",
        "Indonesia",
        "Iran",
        "Israel",
        "Japan",
        "Jordan",
        "Kuwait",
        "Laos",
        "Lebanon",
        "Maldives",
        "Malaysia",
        "Mongolia",
        "Myanmar",
        "Nepal",
        "Oman",
        "Kyrgyzstan",
        "Singapore",
        "Sri Lanka",
        "Thailand",
        "Taiwan",
        "Turkey",
        "Uzbekistan",
        "Vietnam",
        "India",
    }
)

AFRICA = frozenset(
    {
        "Botswana",
        "Cape Verde",
        "Egypt",
        "Ethiopia",
        "Ghana",
        "Madagascar",
        "Morocco",
        "Mauritius",
        "Namibia",
        "Kenya",
        "Rwanda",
        "Seychelles",
        "Senegal",
        "São Tomé and Príncipe",
        "Tanzania",
        "Tunisia",
        "Uganda",
        "Zimbabwe",
        "South Africa",
    }
)

NORTH_AMERICA = frozenset(
    {
        "Aruba",
        "Bahamas",
        "Barbados",
        "Belize",
        "Canada",
        "Costa Rica",
        "Cuba",
        "USA",
        "Grenada",
        "Guatemala",
        "Honduras",
        "U.S. Virgin Islands",
        "Jamaica",
        "Mexico",
        "Nicaragua",
        "Panama",
        "Puerto Rico",
        "Dominican Republic",
        "Saint Lucia",
        "Turks and Caicos",
    }
)

SOUTH_AMERICA = frozenset(
    {
        "Argentina",
        "Bolivia",
        "Brazil",
        "Chile",
        "Colombia",
        "Ecuador",
        "Paraguay",
        "Peru",
        "Uruguay",
        "Venezuela",
    }
)

OCEANIA = frozenset(
    {
        "Australia",
        "Fiji",
        "Cook Islands",
        "New Caledonia",
        "New Zealand",
        "Palau",
        "French Polynesia",
        "Samoa",
        "Vanuatu",
    }
)

# Matches travel.models.TRIP_TYPE_CHOICES's shape (code, label) - used the
# same way in ai.orchestration's INTENT_SCHEMA/prompt.
CONTINENT_CHOICES = [
    ("europe", "Europe"),
    ("asia", "Asia"),
    ("africa", "Africa"),
    ("north_america", "North America"),
    ("south_america", "South America"),
    ("oceania", "Oceania"),
]

COUNTRIES_BY_CONTINENT = {
    "europe": EUROPE,
    "asia": ASIA,
    "africa": AFRICA,
    "north_america": NORTH_AMERICA,
    "south_america": SOUTH_AMERICA,
    "oceania": OCEANIA,
}


def countries_in_continent(continent: str) -> frozenset:
    """Countries (as stored in Destination.country) belonging to the given
    continent code. Returns an empty frozenset for an unrecognized code
    rather than raising - callers treat "no matching countries" the same
    way as "continent not set" (no filtering applied)."""
    return COUNTRIES_BY_CONTINENT.get(continent, frozenset())
