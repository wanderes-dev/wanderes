"""Explicit country-name canonicalization - maps a known alias, English
variant, or Portuguese translation to the exact string
`travel.models.Destination.country` stores for that country in the
curated catalog.

Direct evidence for this module (evaluations baseline, 2026-09-25):
`is_known_country("United States")` returned False because the catalog
stores `"USA"` - the AI's own extraction of "United States" is a
perfectly reasonable standard English name, just not the one this
specific catalog happens to use. Separately, `"Tailândia"` (the
traveler's own Portuguese) never matched `"Thailand"` in an exclusion
list, since `find_destination_slugs_by_name` only ever did a literal
substring match - no translation step existed at all.

Deliberately a small, explicit, hand-maintained table - never fuzzy
matching (an ambiguous or partial name should fail to resolve, not
guess) and never a general-purpose geography database (no lat/lon,
no hierarchies, no synonyms beyond "the same country, a different
name for it"). An alias only needs to exist here for a country
actually in the catalog, and only when its common English/Portuguese
name genuinely differs from the catalog's own stored value - most
country names already match as-is and need no entry.

Covers every catalog country whose Portuguese name meaningfully
differs from English (all 132 catalog countries were reviewed for
this), plus the specific English variants (USA/US/United States/...)
the baseline surfaced.
"""

from __future__ import annotations

# key: alias, lowercased. value: the exact string Destination.country
# stores. Only countries whose common name actually differs from the
# catalog value need an entry - "Portugal", "Argentina", "Chile" etc.
# already match as typed, in either language.
_COUNTRY_ALIASES: dict[str, str] = {
    # English variants found by the evaluation baseline.
    "united states": "USA",
    "united states of america": "USA",
    "us": "USA",
    "u.s.": "USA",
    "u.s.a.": "USA",
    "america": "USA",
    # Portuguese translations, one entry per catalog country whose PT
    # name differs from its English catalog value.
    "estados unidos": "USA",
    "eua": "USA",
    "albânia": "Albania",
    "armênia": "Armenia",
    "austrália": "Australia",
    "áustria": "Austria",
    "azerbaijão": "Azerbaijan",
    "bahrein": "Bahrain",
    "bélgica": "Belgium",
    "butão": "Bhutan",
    "bolívia": "Bolivia",
    "bósnia e herzegovina": "Bosnia and Herzegovina",
    "bósnia": "Bosnia and Herzegovina",
    "botsuana": "Botswana",
    "brasil": "Brazil",
    "camboja": "Cambodia",
    "canadá": "Canada",
    "cabo verde": "Cape Verde",
    "colômbia": "Colombia",
    "ilhas cook": "Cook Islands",
    "croácia": "Croatia",
    "chipre": "Cyprus",
    "república tcheca": "Czech Republic",
    "tchéquia": "Czech Republic",
    "dinamarca": "Denmark",
    "república dominicana": "Dominican Republic",
    "equador": "Ecuador",
    "egito": "Egypt",
    "estônia": "Estonia",
    "etiópia": "Ethiopia",
    "ilhas faroé": "Faroe Islands",
    "finlândia": "Finland",
    "frança": "France",
    "polinésia francesa": "French Polynesia",
    "geórgia": "Georgia",
    "alemanha": "Germany",
    "gana": "Ghana",
    "grécia": "Greece",
    "granada": "Grenada",
    "hungria": "Hungary",
    "islândia": "Iceland",
    "índia": "India",
    "indonésia": "Indonesia",
    "irã": "Iran",
    "irlanda": "Ireland",
    "itália": "Italy",
    "japão": "Japan",
    "jordânia": "Jordan",
    "cazaquistão": "Kazakhstan",
    "quênia": "Kenya",
    "quirguistão": "Kyrgyzstan",
    "letônia": "Latvia",
    "líbano": "Lebanon",
    "lituânia": "Lithuania",
    "luxemburgo": "Luxembourg",
    "malásia": "Malaysia",
    "maldivas": "Maldives",
    "maurício": "Mauritius",
    "méxico": "Mexico",
    "mônaco": "Monaco",
    "mongólia": "Mongolia",
    "marrocos": "Morocco",
    "namíbia": "Namibia",
    "holanda": "Netherlands",
    "países baixos": "Netherlands",
    "nova caledônia": "New Caledonia",
    "nova zelândia": "New Zealand",
    "nicarágua": "Nicaragua",
    "noruega": "Norway",
    "omã": "Oman",
    "panamá": "Panama",
    "paraguai": "Paraguay",
    "filipinas": "Philippines",
    "polônia": "Poland",
    "porto rico": "Puerto Rico",
    "catar": "Qatar",
    "romênia": "Romania",
    "rússia": "Russia",
    "ruanda": "Rwanda",
    "santa lúcia": "Saint Lucia",
    "arábia saudita": "Saudi Arabia",
    "sérvia": "Serbia",
    "seicheles": "Seychelles",
    "singapura": "Singapore",
    "eslováquia": "Slovakia",
    "eslovênia": "Slovenia",
    "áfrica do sul": "South Africa",
    "coreia do sul": "South Korea",
    "corea do sul": "South Korea",
    "espanha": "Spain",
    "suécia": "Sweden",
    "suíça": "Switzerland",
    "são tomé e príncipe": "São Tomé and Príncipe",
    "tanzânia": "Tanzania",
    "tailândia": "Thailand",
    "tunísia": "Tunisia",
    "turquia": "Turkey",
    "turcas e caicos": "Turks and Caicos",
    "ilhas turcas e caicos": "Turks and Caicos",
    "ilhas virgens americanas": "U.S. Virgin Islands",
    "emirados árabes unidos": "United Arab Emirates",
    "reino unido": "United Kingdom",
    "uruguai": "Uruguay",
    "uzbequistão": "Uzbekistan",
    "vietnã": "Vietnam",
    "vietname": "Vietnam",
    "zimbábue": "Zimbabwe",
}


def canonicalize_country_name(raw: str | None) -> str:
    """Resolves a known alias/translation to the exact string the
    catalog stores for that country. Returns the input unchanged
    (stripped) when it isn't a recognized alias - including when it's
    already the canonical form, or a genuinely unknown/foreign country
    this table has no opinion on. Never guesses: an unmapped name just
    passes through for the normal is_known_country() check to accept or
    reject on its own.
    """
    if not raw:
        return raw or ""
    stripped = raw.strip()
    return _COUNTRY_ALIASES.get(stripped.lower(), stripped)
