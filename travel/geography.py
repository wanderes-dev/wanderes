"""Continent classification for Destination.country values.

Added after a real bug: a "Eurotrip" request's recommendation cards
included Bali, Marrakech, Chiang Mai, Hoi An, and Ayutthaya right next
to the actual European options, because the scoring pipeline could
filter by country/trip_type/budget/temperature but had nowhere to put
"Europe" as a hard constraint.

Destination.country stores a specific country name; there's no
continent field on the model and none is added here - a schema change
isn't worth it for a lookup this small and static.
COUNTRIES_BY_CONTINENT is a plain, hand-maintained mapping, classified
against the UN M49 macro-region standard
(https://unstats.un.org/unsd/methodology/m49/) rather than ad hoc
judgment calls, consolidated from the UN's finer sub-regions (e.g.
"Eastern Europe", "Western Asia") down to the 6 continents people
actually name in conversation.

A few transcontinental countries are worth calling out rather than
leaving as a silent choice: Russia is Europe (UN M49 puts it under
Eastern Europe); Turkey, Georgia, Armenia, Azerbaijan, and Cyprus are
Asia (UN M49: Western Asia) - despite Cyprus's and Turkey's EU ties,
this keeps one consistent, citable standard instead of picking and
choosing per country.

The test in test_geography.py guarding coverage of every curated
country will fail if a new catalog country doesn't fit anywhere -
otherwise an unclassified country just quietly never matches any
continent filter. Expect to update this file whenever
curated_destinations.json adds a country not seen before.
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

# Same (code, label) shape as travel.models.TRIP_TYPE_CHOICES - used the
# same way by ai.orchestration's INTENT_SCHEMA/prompt.
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
    """Countries (as stored in Destination.country) in the given
    continent code. An unrecognized code returns an empty frozenset
    instead of raising - callers treat that the same as "no continent
    filter set"."""
    return COUNTRIES_BY_CONTINENT.get(continent, frozenset())
