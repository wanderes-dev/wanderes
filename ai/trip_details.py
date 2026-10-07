"""What the traveler has told us about the trip itself - when it starts, how
long it lasts, who is going - and how that becomes the accommodation search.

One invariant runs through this module: the Booking link, the caption under
it and the facts the reply is written from all come from ONE ResolvedTrip, and
a ResolvedTrip holds only what the traveler actually said. Unknown stays
unknown - no default dates, no default party, no child counted as an adult.

The flow is:

    traveler's words -> components (the model, no arithmetic)
                     -> apply_components() (calendar arithmetic, in code)
                     -> the stored record (the accumulated state's trip_details)
                     -> resolve() -> ResolvedTrip -> URL / caption / facts

The model only ever reports components such as "day 5" or "3 nights"; every
date is computed here, against an explicit `today`.
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta

from django.utils.formats import date_format
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

# An internal sanity bound on a stated stay length (a year), there only to
# refuse obviously pathological input. It is not a statement about what
# Booking accepts: a legitimate long stay goes to the link as the traveler
# said it.
MAX_STAY_LENGTH = 365
MAX_ADULTS = 30
MAX_CHILDREN = 10
MAX_CHILD_AGE = 17  # Booking's own range for a child is 0-17

# The stored record. Every value is what the traveler said or something code
# derived from it at the time they said it (start_date); never the check-out.
EMPTY_RECORD = {
    "start_date": None,  # ISO date, resolved when the traveler said it
    "start_assumed_month": False,  # the traveler gave a day but no month
    "stay_length": None,
    "stay_unit": None,  # "days" | "nights" - the unit they used
    "adults": None,
    "children": None,  # None = unknown, 0 = they said there are none
    "child_ages": None,  # the ages known so far; complete only at len == children
}

TRIP_DETAILS_SYSTEM_PROMPT = (
    "You extract the TRIP DETAILS a traveler states in their latest message, as raw "
    "components. You never calculate a date and never guess: anything not stated in the "
    "latest message is null (or an empty list). Take values only from the traveler's own "
    "words in that message. When the assistant's previous question is shown, it is only "
    "context for what a short reply refers to - never take a number or detail from it. "
    "Ignore anything that isn't about the traveler's own upcoming trip: past trips, "
    "someone else's trip ('my cousin is going on the 12th with three kids' states nothing "
    "about this traveler, whatever dates or people it names), and complaints or questions "
    "about what the assistant said earlier (e.g. asking why the assistant put some number "
    "of people states nothing).\n\n"
    "start - when the trip begins:\n"
    "- day: the day of the month ('dia 5' -> 5, 'on the 12th' -> 12). Null if no day number "
    "is given.\n"
    "- month: 1-12, ONLY if a month is named ('de novembro' -> 11). A day number alone is "
    "never a month: 'dia 05' is day 5 with month null.\n"
    "- year: only if stated.\n"
    "- relative_month: 'this' for 'deste mês'/'this month', 'next' for 'mês que vem'/"
    "'next month'; otherwise null.\n"
    "end - ONLY for an explicit range ('5 a 8', 'from the 5th to the 8th', 'de 5 a 8 de "
    "novembro'): the last day, and its month if named. Put the range's first day in start. "
    "Never work an end day out from a length - 'for a week' or '3 nights' is stay_length, "
    "and end stays null. Null otherwise.\n"
    "stay_length / stay_unit - how long they stay, in the unit they used: '3 dias' -> 3 "
    "'days', '3 noites' -> 3 'nights', 'two weeks' -> 14 'days', 'uma semana' -> 7 'days'. "
    "Null if no length is stated.\n\n"
    "Who is going - adults and children are SEPARATE numbers; never add children to the "
    "adults and never give a total:\n"
    "- adults: the adults traveling, including the traveler ('eu e minha esposa' -> 2, "
    "'sozinho' -> 1, 'somos 4' with no children mentioned -> 4). A bare number answering a "
    "question about how many people is adults. Null if not stated.\n"
    "- children: how many are children - called a child/kid/baby, or a son/daughter with "
    "an age under 18. 0 only when the traveler says there are none. Null if not mentioned.\n"
    "- child_ages: the children's ages in years when stated (a baby under one year is 0), "
    "in the order given; an empty list when not stated. 'meu filho de 5 anos' -> children 1, "
    "child_ages [5]. A reply that only gives an age ('5 anos') after a question about the "
    "child's age -> child_ages [5] with children null. A reply that gives only ages ('tem 6 "
    "anos', 'the eldest is 10 and the other 3') leaves children null: the count was given "
    "earlier.\n\n"
    "cleared_fields - only when the traveler explicitly takes a detail back or says it is "
    "no longer known/decided ('ainda não sei as datas', 'forget the dates', 'sem crianças "
    "afinal' clears children): any of 'start', 'stay', 'adults', 'children', 'child_ages'. "
    "A new value for a detail is a correction, not a clear - report the new value and leave "
    "cleared_fields empty."
)

_DATE_PART = {
    "type": "object",
    "properties": {
        "day": {"type": ["integer", "null"]},
        "month": {"type": ["integer", "null"]},
        "year": {"type": ["integer", "null"]},
        "relative_month": {"type": ["string", "null"], "enum": ["this", "next", None]},
    },
    "required": ["day", "month", "year", "relative_month"],
    "additionalProperties": False,
}

TRIP_DETAILS_SCHEMA = {
    "name": "trip_details_signal",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "start": _DATE_PART,
            "end": {
                "type": "object",
                "properties": {
                    "day": {"type": ["integer", "null"]},
                    "month": {"type": ["integer", "null"]},
                },
                "required": ["day", "month"],
                "additionalProperties": False,
            },
            "stay_length": {"type": ["integer", "null"]},
            "stay_unit": {"type": ["string", "null"], "enum": ["days", "nights", None]},
            "adults": {"type": ["integer", "null"]},
            "children": {"type": ["integer", "null"]},
            "child_ages": {"type": "array", "items": {"type": "integer"}},
            "cleared_fields": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["start", "stay", "adults", "children", "child_ages"],
                },
            },
        },
        "required": [
            "start",
            "end",
            "stay_length",
            "stay_unit",
            "adults",
            "children",
            "child_ages",
            "cleared_fields",
        ],
        "additionalProperties": False,
    },
}


# --- when to ask the model at all ------------------------------------------

# Words (accents and case stripped) that suggest a message is giving trip
# details. A hit only means "worth one extraction call"; a miss on a rare
# phrasing costs a detail, never a wrong one. Deliberately without "um"/"uma"/
# "one": they appear in far too many unrelated messages.
_CUE_WORDS = frozenset(
    """
    dia dias noite noites semana semanas mes meses hoje amanha depois proximo proxima
    data datas duracao date dates duration fecha fechas duracion duree datum dauer durata
    adulto adultos crianca criancas bebe bebes filho filha filhos filhas esposa esposo
    marido mulher namorado namorada casal familia sozinho sozinha pessoa pessoas
    viajante viajantes ano anos somos dois duas tres quatro cinco seis sete oito nove dez
    janeiro fevereiro marco abril maio junho julho agosto setembro outubro novembro
    dezembro
    day days night nights week weeks month months today tomorrow next adult adults child
    children kid kids baby babies son daughter wife husband partner couple family alone
    solo people persons traveler travelers traveller travellers old year years two three
    four five six seven eight nine ten january february march april may june july august
    september october november december
    noche noches mes hoy manana nino nina ninos ninas hijo hija hijos hijas esposa pareja
    personas viajeros viajero anos
    jour jours nuit nuits semaine mois aujourd demain adulte adultes enfant enfants fils
    fille femme mari famille seul seule personne personnes voyageurs ans deux trois
    quatre cinq janvier fevrier mars avril mai juin juillet aout septembre octobre
    novembre decembre
    giorno giorni notte notti settimana settimane mese mesi oggi domani adulti bambino
    bambina bambini bambine figlio figlia moglie marito coppia famiglia persone anni due
    tre quattro cinque gennaio febbraio aprile maggio giugno luglio settembre ottobre
    dicembre
    tag tage nacht nachte woche wochen monat heute morgen erwachsene kind kinder sohn
    tochter frau mann paar familie allein personen jahre januar februar marz mai juni juli
    oktober dezember
    """.split()
)


def _plain_tokens(text: str) -> list[str]:
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.findall(r"[a-z0-9]+", folded)


def has_trip_detail_cues(message: str) -> bool:
    """Whether the message looks like it gives dates, a length of stay, or who
    is travelling: any digit, or a date/duration/people word in a handful of
    languages. Deterministic, no model call."""
    return any(
        any(ch.isdigit() for ch in token) or token in _CUE_WORDS for token in _plain_tokens(message)
    )


def needs_occupancy(record: dict | None) -> bool:
    """True while nobody has said how many adults are travelling - the one
    detail a stays search is held back for."""
    return _normalize(record)["adults"] is None


# Words that name each detail, for deciding whether a message really takes
# THAT detail back. A clear wipes what the traveler told us, so it is only
# honored for a field the message names - "continua com a data errada" is a
# complaint about a date, not a withdrawal of the length and the party. A
# phrasing in a language not listed here clears nothing (the traveler can
# simply state a new value instead).
_CHILDREN_WORDS = """
    crianca criancas kid kids child children bebe bebes filho filha filhos filhas nino nina
    ninos ninas hijo hija hijos hijas enfant enfants fils fille bambino bambina bambini
    bambine figlio figlia kind kinder son daughter baby babies
"""
_CLEAR_VOCABULARY = {
    "start": """
        data datas date dates fecha fechas datum inicio comeco start arrival chegada
        partida ida saida checkin dia day jour giorno tag
    """,
    "stay": """
        duracao duration dias dia noites noite nights night days day semana semanas week
        weeks estadia stay tempo duree jours jour nuits nuit durata giorni giorno notti
        notte dauer tage tag nacht nachte noches noche duracion
    """,
    "adults": """
        adulto adultos adult adults pessoa pessoas people person persons viajante viajantes
        traveler travelers traveller travellers personas persona viajeros personne
        personnes persone personen gente numero number grupo group erwachsene adulte
        adultes adulti
    """,
    "children": _CHILDREN_WORDS,
    "child_ages": _CHILDREN_WORDS
    + " idade idades age ages anos year years edad edades ans eta alter jahre",
}
_CLEAR_VOCABULARY = {field: frozenset(words.split()) for field, words in _CLEAR_VOCABULARY.items()}


def restrict_clears(components: dict, message: str) -> dict:
    """The components with `cleared_fields` cut down to the details the message
    actually names."""
    if not components["cleared_fields"]:
        return components
    tokens = set(_plain_tokens(message))
    kept = [f for f in components["cleared_fields"] if tokens & _CLEAR_VOCABULARY[f]]
    return {**components, "cleared_fields": kept}


def previous_question_for_extraction(history: list[dict] | None, message: str) -> str | None:
    """The assistant's last message, trimmed, for a short reply that needs it
    ('5 anos' answers a question); None for a message that stands alone. Every
    digit is masked so a number the assistant itself said can't be read as
    something the traveler said."""
    if len(_plain_tokens(message)) > 8:
        return None
    for turn in reversed(history or []):
        if turn.get("role") == "assistant":
            return re.sub(r"\d+", "#", str(turn.get("content", "")))[-400:] or None
    return None


# --- model output -> typed components --------------------------------------


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _int_in(value, low: int, high: int) -> int | None:
    return value if _is_int(value) and low <= value <= high else None


def validate_components(raw) -> dict:
    """The model's output coerced into typed components. Anything malformed or
    out of range is dropped (becomes unknown) rather than repaired."""
    raw = raw if isinstance(raw, dict) else {}
    start = raw.get("start") if isinstance(raw.get("start"), dict) else {}
    end = raw.get("end") if isinstance(raw.get("end"), dict) else {}
    relative = start.get("relative_month")
    unit = raw.get("stay_unit")
    length = _int_in(raw.get("stay_length"), 1, MAX_STAY_LENGTH)
    ages_raw, cleared_raw = raw.get("child_ages"), raw.get("cleared_fields")
    ages = [
        a
        for a in (ages_raw if isinstance(ages_raw, list) else [])
        if _int_in(a, 0, 120) is not None
    ]
    cleared = [
        f
        for f in (cleared_raw if isinstance(cleared_raw, list) else [])
        if f in ("start", "stay", "adults", "children", "child_ages")
    ]
    return {
        "start": {
            "day": _int_in(start.get("day"), 1, 31),
            "month": _int_in(start.get("month"), 1, 12),
            "year": _int_in(start.get("year"), 2000, 2200),
            "relative_month": relative if relative in ("this", "next") else None,
        },
        "end": {
            "day": _int_in(end.get("day"), 1, 31),
            "month": _int_in(end.get("month"), 1, 12),
        },
        "stay_length": length,
        # A length with no unit is read as days; both count as nights anyway.
        "stay_unit": (unit if unit in ("days", "nights") else "days") if length else None,
        "adults": _int_in(raw.get("adults"), 1, MAX_ADULTS),
        "children": _int_in(raw.get("children"), 0, MAX_CHILDREN),
        "child_ages": ages,
        "cleared_fields": cleared,
    }


# --- the stored record ------------------------------------------------------


def _parse_iso(value) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _normalize(record) -> dict:
    """A stored record as a full, well-typed dict; anything that doesn't
    check out reads as unknown."""
    out = dict(EMPTY_RECORD)
    if not isinstance(record, dict):
        return out
    if _parse_iso(record.get("start_date")) is not None:
        out["start_date"] = record["start_date"]
        out["start_assumed_month"] = bool(record.get("start_assumed_month"))
    length = _int_in(record.get("stay_length"), 1, MAX_STAY_LENGTH)
    if length and record.get("stay_unit") in ("days", "nights"):
        out["stay_length"] = length
        out["stay_unit"] = record["stay_unit"]
    out["adults"] = _int_in(record.get("adults"), 1, MAX_ADULTS)
    children = _int_in(record.get("children"), 0, MAX_CHILDREN)
    out["children"] = children
    ages = record.get("child_ages")
    if children and isinstance(ages, list):
        kept = [a for a in ages if _int_in(a, 0, MAX_CHILD_AGE) is not None]
        if kept and len(kept) <= children:
            out["child_ages"] = kept
    return out


def _stored(record: dict) -> dict | None:
    """The record to persist: None when nothing is known."""
    return None if record == EMPTY_RECORD else record


@dataclass(frozen=True)
class Issue:
    """Something the traveler said that couldn't be used; the reply asks."""

    code: str  # "start_in_past" | "invalid_date" | "end_not_after_start"
    when: date | None = None


@dataclass(frozen=True)
class Applied:
    record: dict | None
    changed: bool
    issues: tuple[Issue, ...] = ()
    # The traveler just told us about a child without an age: ask for it, once.
    ask_child_ages: bool = False


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def _resolve_start(
    start: dict, today: date, *, prior: date | None = None, prior_assumed: bool = False
) -> tuple[date | None, bool, Issue | None]:
    """(start date, month was assumed, problem). All the calendar arithmetic
    for a start date lives here. `prior` is the start already on record: a
    bare day then reads as a correction within that month ("na verdade dia
    8" after "dia 5" stays in the same month), not a fresh "next time it
    comes round"."""
    day, month, year, relative = (
        start["day"],
        start["month"],
        start["year"],
        start["relative_month"],
    )
    if day is None:
        return None, False, None  # no day number: nothing to place on the calendar

    if relative is not None or month is not None:
        if relative == "this":
            y, m = today.year, today.month
        elif relative == "next":
            y, m = _next_month(today.year, today.month)
        else:
            y, m = year, month
        if y is None:
            # A month with no year: the next time it comes round.
            candidate = _safe_date(today.year, m, day)
            if candidate is not None and candidate < today:
                candidate = _safe_date(today.year + 1, m, day)
        else:
            candidate = _safe_date(y, m, day)
        if candidate is None:
            return None, False, Issue("invalid_date")
        if candidate < today:
            # Said outright ("this month", a dated year) and already gone: ask,
            # never roll it forward behind their back.
            return None, False, Issue("start_in_past", candidate)
        return candidate, False, None

    # Only a day number. A correction of a start still ahead keeps its month.
    if prior is not None and prior >= today:
        candidate = _safe_date(prior.year, prior.month, day)
        if candidate is not None and candidate >= today:
            return candidate, prior_assumed, None
    # Otherwise: the next time that day of the month comes round.
    y, m = today.year, today.month
    for _attempt in range(14):
        candidate = _safe_date(y, m, day)
        if candidate is not None and candidate >= today:
            return candidate, True, None
        y, m = _next_month(y, m)
    return None, False, Issue("invalid_date")


def _resolve_range_end(base: date, end: dict) -> tuple[date | None, Issue | None]:
    day, month = end["day"], end["month"]
    if month is None:
        y, m = base.year, base.month
        for _attempt in range(3):  # "28 a 3": the 3rd is next month
            candidate = _safe_date(y, m, day)
            if candidate is not None and candidate > base:
                return candidate, None
            y, m = _next_month(y, m)
        return None, Issue("invalid_date")
    candidate = _safe_date(base.year, month, day)
    if candidate is not None and candidate <= base and month < base.month:
        candidate = _safe_date(base.year + 1, month, day)  # "28 dez a 3 jan"
    if candidate is None:
        return None, Issue("invalid_date")
    if candidate <= base:
        return None, Issue("end_not_after_start")
    return candidate, None


def _merge_ages(existing: list | None, new: list[int], children: int | None) -> list | None:
    """Ages arrive in pieces ('a mais velha tem 7'): a full set replaces what
    was there, a partial one is added to it while it still fits."""
    if not children or not new:
        return existing
    if len(new) == children:
        return list(new)
    if len(new) > children:
        return existing
    if existing and len(existing) + len(new) <= children:
        return [*existing, *new]
    return list(new)


def apply_components(current: dict | None, components: dict, today: date) -> Applied:
    """Fold what the traveler just said into the stored record. A new value
    replaces the old one (that is what a correction is), an explicit clear
    drops it, anything not mentioned stays as it was. Derived values are never
    stored, so a corrected start date or length simply moves the check-out."""
    before = _normalize(current)
    rec = dict(before)
    issues: list[Issue] = []

    for field_name in components["cleared_fields"]:
        if field_name == "start":
            rec["start_date"], rec["start_assumed_month"] = None, False
        elif field_name == "stay":
            rec["stay_length"], rec["stay_unit"] = None, None
        elif field_name == "adults":
            rec["adults"] = None
        elif field_name == "children":
            rec["children"], rec["child_ages"] = None, None
        elif field_name == "child_ages":
            rec["child_ages"] = None

    start_date = None
    if any(v is not None for v in components["start"].values()):
        start_date, assumed, issue = _resolve_start(
            components["start"],
            today,
            prior=_parse_iso(before["start_date"]),
            prior_assumed=before["start_assumed_month"],
        )
        if issue is not None:
            issues.append(issue)
        elif start_date is not None:
            rec["start_date"] = start_date.isoformat()
            rec["start_assumed_month"] = assumed

    if components["stay_length"] is not None:
        # A length the traveler stated outright beats an end day, which would
        # only ever be the model's arithmetic ("uma semana" -> the 22nd).
        rec["stay_length"], rec["stay_unit"] = components["stay_length"], components["stay_unit"]
    elif components["end"]["day"] is not None:
        base = start_date or _parse_iso(rec["start_date"])
        if base is not None:
            end_date, issue = _resolve_range_end(base, components["end"])
            if issue is not None:
                issues.append(issue)
            else:
                rec["stay_length"], rec["stay_unit"] = (end_date - base).days, "nights"

    if components["adults"] is not None:
        rec["adults"] = components["adults"]
    ages = components["child_ages"]
    children = components["children"]
    if children is not None and ages and before["children"] and children == len(ages):
        if children < before["children"]:
            # Some ages of a bigger group ("a de 5 anos"), not a smaller party:
            # never let an answer about ages quietly drop a child we know of.
            children = None
    if children is not None:
        rec["children"] = children
        if children == 0 or children != before["children"]:
            rec["child_ages"] = None  # the old ages were for a different group
    if ages and rec["children"]:
        kids = [a for a in ages if a <= MAX_CHILD_AGE]
        grown = len(ages) - len(kids)
        if grown:
            # Eighteen or over is an adult to Booking, whatever we first called them.
            rec["adults"] = (rec["adults"] or 0) + grown
            rec["children"] = max(rec["children"] - grown, 0)
        rec["child_ages"] = _merge_ages(rec["child_ages"], kids, rec["children"])
    if not rec["children"]:
        rec["child_ages"] = None

    rec = _normalize(rec)
    # Ask when this message moved the children's details forward without
    # completing them: a child mentioned with no age, or some ages of several.
    ask = (
        bool(rec["children"])
        and len(rec["child_ages"] or []) != rec["children"]
        and (rec["children"] != before["children"] or rec["child_ages"] != before["child_ages"])
    )
    return Applied(_stored(rec), rec != before, tuple(issues), ask)


# --- the single resolved view -----------------------------------------------


@dataclass(frozen=True)
class ResolvedTrip:
    """What is known about the trip right now, as one object. The URL, the
    caption and the reply's facts are all read from this."""

    check_in: date | None = None
    check_out: date | None = None
    nights: int | None = None
    start_assumed_month: bool = False
    stay_length: int | None = None
    stay_unit: str | None = None
    adults: int | None = None
    children: int | None = None
    child_ages: tuple[int, ...] = ()
    # Why a known detail isn't in the search.
    start_date_past: bool = False

    @property
    def has_dates(self) -> bool:
        return self.check_in is not None and self.check_out is not None

    @property
    def children_complete(self) -> bool:
        """Every child's age is known - the only case children go in the search."""
        return bool(self.children) and len(self.child_ages) == self.children

    @property
    def children_pending(self) -> bool:
        return bool(self.children) and not self.children_complete

    @property
    def is_informative(self) -> bool:
        return (
            self.has_dates
            or self.stay_length is not None
            or self.adults is not None
            or bool(self.children)
            or self.start_date_past
        )

    def booking_kwargs(self) -> dict:
        """The keyword arguments for build_search_url, holding exactly what is
        known and safe: dates as a pair or not at all, adults, and children
        only together with all their ages (Booking would otherwise quietly
        read a child with no age as age 0)."""
        kwargs: dict = {}
        if self.has_dates:
            kwargs["check_in"], kwargs["check_out"] = self.check_in, self.check_out
        if self.adults is not None:
            kwargs["adults"] = self.adults
            if self.children_complete:
                kwargs["children"] = self.children
                kwargs["child_ages"] = list(self.child_ages)
        return kwargs

    # -- the readable forms ------------------------------------------------

    def _dates_text(self) -> str:
        if self.has_dates:
            text = _("%(check_in)s – %(check_out)s (%(nights)s)") % {
                "check_in": date_format(self.check_in, "j M Y"),
                "check_out": date_format(self.check_out, "j M Y"),
                "nights": ngettext("%(n)d night", "%(n)d nights", self.nights) % {"n": self.nights},
            }
            if self.start_assumed_month:
                return _("%(dates)s, month assumed") % {"dates": text}
            return text
        if self.start_date_past:
            return _("no dates set (the start date has already passed)")
        if self.stay_length is not None:
            return _("no dates set (a start date is needed)")
        return _("no dates set")

    def _adults_text(self) -> str:
        if self.adults is None:
            return _("travelers not set")
        return ngettext("%(n)d adult", "%(n)d adults", self.adults) % {"n": self.adults}

    def _children_text(self) -> str | None:
        if not self.children:
            return None
        count = ngettext("%(n)d child", "%(n)d children", self.children) % {"n": self.children}
        if self.children_complete and self.adults is not None:
            ages = ", ".join(str(a) for a in self.child_ages)
            return _("%(count)s (age %(ages)s)") % {"count": count, "ages": ages}
        if self.children_complete:
            return _("%(count)s not included yet - the number of adults is needed") % {
                "count": count
            }
        return _("%(count)s not included yet - the age is needed") % {"count": count}

    def caption(self, place: str) -> str:
        """The line shown under the "Search stays" button: exactly what the
        link carries, and what is known but left out of it."""
        parts = [place, self._dates_text(), self._adults_text()]
        children = self._children_text()
        if children:
            parts.append(children)
        return _("Booking search: %(parts)s") % {"parts": " · ".join(parts)}


def resolve(record: dict | None, today: date) -> ResolvedTrip:
    """The pure resolver: a stored record plus today's date, nothing else."""
    rec = _normalize(record)
    start = _parse_iso(rec["start_date"])
    start_past = start is not None and start < today
    if start_past:
        start = None
    nights = rec["stay_length"]  # "3 dias" and "3 noites" are both 3 nights
    check_in = check_out = None
    if start is not None and nights is not None:
        check_in, check_out = start, start + timedelta(days=nights)
    ages = tuple(rec["child_ages"] or ())
    return ResolvedTrip(
        check_in=check_in,
        check_out=check_out,
        nights=nights,
        start_assumed_month=rec["start_assumed_month"] and check_in is not None,
        stay_length=rec["stay_length"],
        stay_unit=rec["stay_unit"],
        adults=rec["adults"],
        children=rec["children"],
        child_ages=ages,
        start_date_past=start_past,
    )


# --- what the reply is told --------------------------------------------------


@dataclass(frozen=True)
class TripTurn:
    """The trip state for one turn: the resolved trip, plus what this turn's
    message raised (a date that couldn't be used, a child without an age)."""

    trip: ResolvedTrip
    issues: tuple[Issue, ...] = ()
    ask_child_ages: bool = False
    today: date | None = None
    # This message changed what the search link carries, so the one the
    # traveler last saw (if any) is out of date. A detail the link doesn't
    # carry (a length with no start date, a child still waiting for an age)
    # doesn't count: nothing about the link would be new.
    changed: bool = False

    @property
    def is_informative(self) -> bool:
        return self.trip.is_informative or bool(self.issues) or self.ask_child_ages


def _english_date(d: date) -> str:
    return f"{d:%A} {d.day} {d:%B} {d.year}"


def _issue_line(issue: Issue, today: date | None) -> str:
    if issue.code == "start_in_past" and issue.when is not None:
        return (
            f"The traveler gave a start date that falls on {_english_date(issue.when)}, which "
            f"has already passed (today is {_english_date(today) if today else 'later'}). "
            "Nothing was changed. Ask which date they mean."
        )
    if issue.code == "end_not_after_start":
        return "The traveler gave an end date that is not after the start. Ask them to confirm."
    return "The traveler gave a date that doesn't exist on the calendar. Ask them to restate it."


def fact_block(turn: TripTurn | None, *, always: bool = False) -> str:
    """The trip facts for a reply prompt. Empty when there's nothing to say
    (unless `always`, for the stays replies, where "nothing is set" is itself
    the fact). The reply may state dates and numbers of travelers only as
    listed here."""
    if turn is None or not (always or turn.is_informative):
        return ""
    trip = turn.trip
    lines = [
        "Trip details Wanderes holds for this traveler - the ONLY dates, stay length and "
        "numbers of travelers you may state. Never calculate, infer or restate any other, and "
        "never say a detail was set, changed or corrected unless it is listed here:"
    ]
    if trip.has_dates:
        assumed = (
            " The traveler gave only the day; the month was assumed as the next time that day "
            "comes round - say so."
            if trip.start_assumed_month
            else ""
        )
        counted = (
            f' The traveler said "{trip.stay_length} days", counted as {trip.nights} nights.'
            if trip.stay_unit == "days"
            else ""
        )
        lines.append(f"- Check-in: {_english_date(trip.check_in)}.{assumed}")
        check_out = _english_date(trip.check_out)
        lines.append(f"- Check-out: {check_out} ({trip.nights} nights).{counted}")
    elif trip.start_date_past:
        lines.append("- Dates: none - the start date they gave has already passed.")
    elif trip.stay_length is not None:
        lines.append(
            f"- Stay: {trip.stay_length} {trip.stay_unit} (counted as {trip.nights} nights), but "
            "no start date yet, so the search carries no dates."
        )
    else:
        lines.append("- Dates: none set. The search carries no dates.")
    lines.append(
        f"- Adults: {trip.adults}." if trip.adults is not None else "- Travelers: not stated yet."
    )
    if trip.children_complete and trip.adults is not None:
        ages = ", ".join(str(a) for a in trip.child_ages)
        lines.append(f"- Children: {trip.children}, ages {ages} - included in the search.")
    elif trip.children_complete:
        lines.append(
            f"- Children: {trip.children} (ages known), but nobody has said how many adults are "
            "travelling, so they are not in the Booking search yet."
        )
    elif trip.children_pending:
        lines.append(
            f"- Children: {trip.children}, but the age is not known yet, so the "
            "child is NOT included in the Booking search until it is. Never count a child as an "
            "adult and never guess an age."
            if trip.children == 1
            else f"- Children: {trip.children}, but not every age is known yet, so the children "
            "are NOT included in the Booking search until all ages are. Never count a child as an "
            "adult and never guess an age."
        )
    carried = []
    if trip.has_dates:
        carried.append(f"dates {trip.check_in.isoformat()} to {trip.check_out.isoformat()}")
    if trip.adults is not None:
        carried.append(f"{trip.adults} adults")
        if trip.children_complete:
            carried.append(f"{trip.children} children")
    lines.append(
        "- The Booking search link carries exactly: "
        + (", ".join(carried) if carried else "only the destination")
        + ". Nothing else."
    )
    for issue in turn.issues:
        lines.append("- Needs clarification: " + _issue_line(issue, turn.today))
    if turn.ask_child_ages:
        lines.append(
            "- The traveler just mentioned a child without an age: ask for the age (each age, "
            "if several), once and briefly, because Booking needs it to price the stay."
        )
    return "\n".join(lines) + "\n\n"
