"""Destination-name equivalence for evaluation grounding checks only -
never used by production code or by recommendation ranking.

Cycle 1's baseline comparison flagged `winner_mentioned` false positives
where the deterministic #1 destination genuinely was presented first
(Fix A working as intended), but a plain ASCII substring check didn't
recognize the AI's own reply text as referring to it:

- "Brasov" (the catalog's plain-ASCII `Destination.name`) vs "Brașov"
  (the AI's Portuguese reply, correctly using the real Romanian
  diacritic) - a textual normalization difference, not a different name.
- "Rome" (the catalog's English name) vs "Roma" (the AI's Portuguese
  reply) - a genuinely different word (a Portuguese exonym), not a
  spelling variant - no amount of unicode normalization makes these
  equal, so this needs an explicit alias.

Two independent, conservative mechanisms, applied together - never
unrestricted fuzzy matching, which risks a false match between two
unrelated but similarly-spelled destinations (the traveler's actual
"Paris must not accidentally match [something else]" requirement):

1. `normalize_for_comparison()` - Unicode NFKD decomposition + stripping
   combining marks (diacritics) + casefold. Purely mechanical, no
   guessing - "Brașov" and "Brasov" normalize to the same string,
   "Rome" and "Roma" do NOT (they differ by more than accents).
2. `_DESTINATION_NAME_ALIASES` - a small, explicit, hand-verified table
   of well-established Portuguese exonyms for catalog destinations
   whose common Portuguese name is a genuinely different word from the
   catalog's English `name` (not just an accent). Bounded on purpose -
   only real catalog destinations, only names actually different enough
   that normalization alone can't bridge them. An unmapped destination
   is judged on exact/normalized matching only, never guessed.
"""

from __future__ import annotations

import re
import unicodedata

# key: catalog Destination.slug. value: the Portuguese exonym(s) an AI
# reply might reasonably use instead of the catalog's own English
# `name` - well-established Portuguese names for major world cities,
# verified one by one against the real catalog's actual `name` field
# (not guessed, and not simply restating the English name back).
#
# A single accented Portuguese spelling per entry is enough -
# normalize_for_comparison() already strips diacritics on both sides of
# any comparison, so an unaccented variant would just be redundant.
_DESTINATION_NAME_ALIASES: dict[str, tuple[str, ...]] = {
    "roma-it": ("Roma",),
    "veneza-it": ("Veneza",),
    "florenca-it": ("Florença",),
    "milao-it": ("Milão",),
    "toquio-jp": ("Tóquio",),
    "moscou-ru": ("Moscou",),
    "sao-petersburgo-ru": ("São Petersburgo",),
    "atenas-gr": ("Atenas",),
    "viena-at": ("Viena",),
    "varsovia-pl": ("Varsóvia",),
    "praga-cz": ("Praga",),
    "bucareste-ro": ("Bucareste",),
    "belgrado-rs": ("Belgrado",),
    "liubliana-si": ("Liubliana",),
    "nova-york-us": ("Nova York",),
    "cidade-do-mexico-mx": ("Cidade do México",),
    "cidade-do-cabo-za": ("Cidade do Cabo",),
    "joanesburgo-za": ("Joanesburgo",),
    "pequim-cn": ("Pequim",),
    "xangai-cn": ("Xangai",),
    "seul-kr": ("Seul",),
    "lisboa-pt": ("Lisboa",),
    "amsterda-nl": ("Amsterdã",),
    "bruxelas-be": ("Bruxelas",),
    "copenhague-dk": ("Copenhague",),
    "estocolmo-se": ("Estocolmo",),
    "gotemburgo-se": ("Gotemburgo",),
    "helsinque-fi": ("Helsinque",),
    "munique-de": ("Munique",),
    "zurique-ch": ("Zurique",),
    "assuncao-py": ("Assunção",),
}


def normalize_for_comparison(text: str) -> str:
    """Casefolds and strips diacritics/combining marks via Unicode NFKD
    decomposition - "Brașov" and "Brasov" collapse to the same string.
    Never changes which letters are present, only how they're encoded -
    "Rome" and "Roma" stay genuinely different after this."""
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return without_marks.casefold()


def destination_name_variants(slug: str, canonical_name: str) -> tuple[str, ...]:
    """All names a grounding check should accept as referring to this
    destination - the catalog's own name plus any explicit alias on
    file for its slug. Always includes the canonical name itself, so a
    destination with no alias entry still works normally."""
    return (canonical_name, *_DESTINATION_NAME_ALIASES.get(slug, ()))


def mentions_destination(reply: str, *, slug: str, name: str, country: str) -> bool:
    """Whether `reply` refers to this destination by any known-equivalent
    form of its name or country - normalized-diacritic match, or an
    explicit alias, never unrestricted fuzzy matching. A destination
    with no alias and no diacritic difference behaves like a plain
    substring check, except that the match must land on whole-word
    boundaries.

    The whole-word requirement is deliberate, not a stylistic choice: a
    plain `in` substring check on the normalized alias "roma" (Rome)
    matches inside the unrelated Portuguese word "romantica"
    ("romantic") - exactly the "Paris must not accidentally match an
    unrelated similarly spelled destination" failure mode this module
    exists to avoid. `\\b` boundaries on both sides close that gap
    without needing a token-by-token tokenizer."""
    reply_normalized = normalize_for_comparison(reply)
    candidates = destination_name_variants(slug, name) + (country,)
    for candidate in candidates:
        normalized_candidate = normalize_for_comparison(candidate)
        if not normalized_candidate:
            continue
        if re.search(rf"\b{re.escape(normalized_candidate)}\b", reply_normalized):
            return True
    return False
