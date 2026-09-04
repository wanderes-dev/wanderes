"""Continent classification for Destination.country values (2026-09-04,
real production bug: a "Eurotrip" request's recommendation cards
included Bali, Marrakech, Chiang Mai, Hoi An, and Ayutthaya alongside the
genuinely European options - the deterministic scoring pipeline had no
way to filter by continent at all, only country/trip_type/budget/
temperature, so "Europe" as a hard constraint had nowhere to go).

Destination.country stores a specific country name (in Portuguese,
matching the curated dataset's authoring language) - there is no
continent field on the model, and none is added here either; a schema
change/migration isn't needed for a lookup this small and static.
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
        "Albânia",
        "Alemanha",
        "Andorra",
        "Bélgica",
        "Bósnia e Herzegovina",
        "Croácia",
        "Dinamarca",
        "Eslováquia",
        "Eslovênia",
        "Espanha",
        "Estônia",
        "Finlândia",
        "França",
        "Grécia",
        "Hungria",
        "Ilhas Faroe",
        "Irlanda",
        "Islândia",
        "Itália",
        "Letônia",
        "Lituânia",
        "Luxemburgo",
        "Malta",
        "Montenegro",
        "Mônaco",
        "Noruega",
        "Países Baixos",
        "Polônia",
        "Portugal",
        "Reino Unido",
        "República Tcheca",
        "Romênia",
        "Rússia",
        "Suécia",
        "Suíça",
        "Sérvia",
        "Áustria",
    }
)

ASIA = frozenset(
    {
        "Armênia",
        "Arábia Saudita",
        "Azerbaijão",
        "Bahrein",
        "Butão",
        "Camboja",
        "Catar",
        "Cazaquistão",
        "China",
        "Chipre",
        "Coreia do Sul",
        "Emirados Árabes Unidos",
        "Filipinas",
        "Geórgia",
        "Indonésia",
        "Irã",
        "Israel",
        "Japão",
        "Jordânia",
        "Kuwait",
        "Laos",
        "Líbano",
        "Maldivas",
        "Malásia",
        "Mongólia",
        "Myanmar",
        "Nepal",
        "Omã",
        "Quirguistão",
        "Singapura",
        "Sri Lanka",
        "Tailândia",
        "Taiwan",
        "Turquia",
        "Uzbequistão",
        "Vietnã",
        "Índia",
    }
)

AFRICA = frozenset(
    {
        "Botswana",
        "Cabo Verde",
        "Egito",
        "Etiópia",
        "Gana",
        "Madagascar",
        "Marrocos",
        "Maurício",
        "Namíbia",
        "Quênia",
        "Ruanda",
        "Seicheles",
        "Senegal",
        "São Tomé e Príncipe",
        "Tanzânia",
        "Tunísia",
        "Uganda",
        "Zimbábue",
        "África do Sul",
    }
)

NORTH_AMERICA = frozenset(
    {
        "Aruba",
        "Bahamas",
        "Barbados",
        "Belize",
        "Canadá",
        "Costa Rica",
        "Cuba",
        "EUA",
        "Granada",
        "Guatemala",
        "Honduras",
        "Ilhas Virgens Americanas",
        "Jamaica",
        "México",
        "Nicarágua",
        "Panamá",
        "Porto Rico",
        "República Dominicana",
        "Santa Lúcia",
        "Turks e Caicos",
    }
)

SOUTH_AMERICA = frozenset(
    {
        "Argentina",
        "Bolívia",
        "Brasil",
        "Chile",
        "Colômbia",
        "Equador",
        "Paraguai",
        "Peru",
        "Uruguai",
        "Venezuela",
    }
)

OCEANIA = frozenset(
    {
        "Austrália",
        "Fiji",
        "Ilhas Cook",
        "Nova Caledônia",
        "Nova Zelândia",
        "Palau",
        "Polinésia Francesa",
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
