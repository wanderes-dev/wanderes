"""Explanation grounding: structural, regex/substring checks that the
AI-generated reply doesn't drift from what the application actually
computed and handed it (05_AI_DESIGN.md §7's "never invent" doctrine,
checked mechanically instead of trusted on faith).

These are deliberately narrow and heuristic - matching phrasing, not
meaning. A reply that fabricates a price in an unusual phrasing this
module doesn't recognize will slip through; see documentation for the
full list of what grounding checks here do NOT reliably catch. Prefer a
false negative (missed violation) over a false positive (flagging an
honest reply) - each pattern below was chosen to be reasonably
distinctive of an actual violation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from recommendations.scoring import ScoredDestination

from .destination_equivalence import mentions_destination

# Phrases that would only make sense if the model had actually queried a
# live pricing/availability/booking source - which stream_travel_recommendation
# never does (integrations.accommodations only ever builds a Booking.com
# *search* URL client-side; nothing in the explanation path calls it).
_LIVE_PRICE_PATTERNS = [
    r"\bstarting (?:at|from) \$?\d",
    r"\bcurrent(?:ly)? price[sd]?\b",
    r"\bprices? (?:start|starting) (?:at|from)\b",
    r"\$\s?\d+\s*(?:/|\bper\b)\s*night",
    r"\b\d+\s*(?:€|eur|usd|\$)\s*(?:/|\bper\b)\s*night",
]

_AVAILABILITY_CLAIM_PATTERNS = [
    r"\bi (?:checked|found|see) availability\b",
    r"\bavailable rooms? (?:right now|currently)\b",
    r"\bi (?:checked|found) (?:a room|flights?|hotels?) for you\b",
    r"\bcurrently available\b",
]

_PROVIDER_CONSULTATION_PATTERNS = [
    r"\baccording to booking\.com\b",
    r"\bi (?:checked|searched|looked (?:it |this )?up on) "
    r"(?:booking\.com|kayak|expedia|skyscanner)\b",
    r"\bbased on (?:real-?time|live) (?:prices|data|availability)\b",
]

_FABRICATED_RATING_PATTERNS = [
    r"\brated\s+\d(?:\.\d)?\s*(?:/|\bout of\b)\s*\d",
    r"\b\d(?:\.\d)?\s*stars?\b",
    r"\b\d+\s*reviews?\b",
]


@dataclass(frozen=True)
class GroundingResult:
    name: str
    passed: bool
    detail: str = ""


def _no_pattern_matches(reply: str, patterns: list[str], check_name: str) -> GroundingResult:
    reply_lower = reply.lower()
    for pattern in patterns:
        match = re.search(pattern, reply_lower)
        if match:
            return GroundingResult(check_name, False, f"matched {pattern!r}: {match.group(0)!r}")
    return GroundingResult(check_name, True, "clean")


def check_winner_mentioned(reply: str, scored: list[ScoredDestination]) -> GroundingResult:
    """Cycle 1.5 (2026-09-25): uses destination_equivalence.mentions_destination
    instead of a raw substring check - Cycle 1's comparison run found
    two false positives (Fix A correctly presented the real #1 first in
    both cases) purely from textual representation differences: "Brasov"
    vs the AI's "Brașov" (a diacritic), and "Rome" vs the AI's "Roma" (a
    Portuguese exonym). Still conservative, never unrestricted fuzzy
    matching - see that module's docstring for exactly what it does and
    doesn't accept."""
    if not scored:
        return GroundingResult("winner_mentioned", True, "no recommendations to check against")
    winner = scored[0].destination
    mentioned = mentions_destination(
        reply, slug=winner.slug, name=winner.name, country=winner.country
    )
    if mentioned:
        detail = "clean"
    else:
        detail = (
            f"neither {winner.name!r} nor {winner.country!r} "
            "(nor a known alias) appears in the reply"
        )
    return GroundingResult("winner_mentioned", mentioned, detail)


def check_no_live_price_claim(reply: str) -> GroundingResult:
    return _no_pattern_matches(reply, _LIVE_PRICE_PATTERNS, "no_live_price_claim")


def check_no_availability_claim(reply: str) -> GroundingResult:
    return _no_pattern_matches(reply, _AVAILABILITY_CLAIM_PATTERNS, "no_availability_claim")


def check_no_provider_consultation_claim(reply: str) -> GroundingResult:
    return _no_pattern_matches(
        reply, _PROVIDER_CONSULTATION_PATTERNS, "no_provider_consultation_claim"
    )


def check_no_fabricated_rating_or_review(reply: str) -> GroundingResult:
    return _no_pattern_matches(reply, _FABRICATED_RATING_PATTERNS, "no_fabricated_rating_or_review")


def run_grounding_checks(reply: str, scored: list[ScoredDestination]) -> list[GroundingResult]:
    return [
        check_winner_mentioned(reply, scored),
        check_no_live_price_claim(reply),
        check_no_availability_claim(reply),
        check_no_provider_consultation_claim(reply),
        check_no_fabricated_rating_or_review(reply),
    ]
