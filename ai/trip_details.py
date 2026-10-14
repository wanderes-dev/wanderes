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
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
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
MAX_PEOPLE_ADDED = 10  # people who join in one message
MAX_ROOMS = 10

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
    "rooms": None,  # how many rooms they asked for (never adults, never children)
    # A month the traveler named with no day yet ("em janeiro"), and the year only if
    # they said one. Partial information: it is never a start date and never reaches
    # the search; a later bare day completes it, a full date replaces it.
    "start_month": None,
    "start_year": None,
    # The party size on the profile that the assistant just asked about. It lives
    # for the one reply that follows, only ever becomes `adults` when the traveler
    # clearly says yes, and is never read for the search.
    "adults_offer": None,
    # The turn on which a relative change ("add a night") was last applied, so the
    # same turn processed twice (a retry) never applies it twice.
    "delta_turn": None,
    # The same for the party: the turn on which someone was last added or a child's age
    # corrected ("mais um amigo", "o mais velho tem 19"), so a turn run twice never does it twice.
    "party_turn": None,
}
# Keys that are bookkeeping or partial information rather than trip details; they are
# left out of the stored record while empty so it looks as it always did.
_OPTIONAL_KEYS = ("adults_offer", "start_month", "start_year", "delta_turn", "party_turn")

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
    "never a month: 'dia 05' is day 5 with month null. A month with no day ('em janeiro', "
    "'in March', 'mid-April') is month only: day null, the day may come later.\n"
    "- year: only if stated.\n"
    "- relative_month: 'this' for 'deste mês'/'this month', 'next' for 'mês que vem'/"
    "'next month'; otherwise null.\n"
    "end - ONLY for an explicit range ('5 a 8', 'from the 5th to the 8th', 'de 5 a 8 de "
    "novembro'): the last day, and its month if named. Put the range's first day in start. "
    "Also for a lone day on which they come back ('volto dia 20', 'regreso el 20', 'we fly "
    "home on the 20th'): that day is end and start stays null - a return day is never the "
    "start. Never work an end day out from a length - 'for a week' or '3 nights' is "
    "stay_length, and end stays null. Null otherwise.\n"
    "stay_length / stay_unit - how long they stay, in the unit they used: '3 dias' -> 3 "
    "'days', '3 noites' -> 3 'nights', 'two weeks' -> 14 'days', 'uma semana' -> 7 'days'. "
    "Null if no length is stated.\n"
    "stay_change - ONLY a change relative to the stay already planned ('add one night', "
    "'mais uma noite', 'una noche más', 'one day less', 'tira uma noite', 'add a night at "
    "the start'): nights_delta is the signed number of nights (+1, -1, +2); at is 'start' "
    "when the night is added or removed at the beginning ('at the start', 'no começo', "
    "'antes'), 'end' when at the end, null when not said. shift_days is for moving the "
    "dates ('we arrive a day later', 'saímos um dia antes'): the signed number of days, "
    "with nights_delta null. A new total ('make it 8 nights', 'actually 10 days') is "
    "stay_length, never stay_change. All null otherwise.\n\n"
    "Who is going - adults and children are SEPARATE numbers; never add children to the "
    "adults and never give a total:\n"
    "- adults: the adults traveling, including the traveler ('eu e minha esposa' -> 2, "
    "'sozinho' -> 1, 'somos 4' with no children mentioned -> 4). A bare number answering a "
    "question about how many people is adults. Mentioning a child does not make the "
    "traveler a counted adult: 'and a child of 6' states no adults. When a total is given "
    "together with how many of them are children ('somos cuatro, dos niños', 'we are 5, 2 "
    "are kids'), adults is the total minus the children (2 and 3), never the total. Null if "
    "not stated.\n"
    "- children: how many are children - called a child/kid/baby, or a son/daughter with "
    "an age. A son or daughter aged 18 or over is still reported here with that age "
    "('eu, minha mulher e nosso filho de 19 anos' -> adults 2, children 1, child_ages "
    "[19]): the application counts anyone 18 or over as an adult, so never drop them and "
    "never add them to adults yourself. A niece, nephew, grandchild, godchild or "
    "stepchild who is coming is reported the same way, with their age when it is given "
    "('e vamos levar minha sobrinha de 7 anos' -> children 1, child_ages [7], adults "
    "null) and as one child with no age when it is not - the application then asks for "
    "it, because the age decides whether they count as a child. 0 only when the "
    "traveler says there are none. Null if not mentioned; a reply that only gives an age "
    "('5 anos') mentions no child.\n"
    "- children_among_counted: true ONLY when the children are part of a group of people "
    "already counted earlier ('dos de ellos son niños', 'dois deles são crianças', 'two of "
    "us are kids'), so they are not additional people. False otherwise - including when a "
    "total comes with the children in the same message (adults is then the total minus "
    "the children) and when children are added ('and two kids').\n"
    "- age_correction: ONLY when the traveler corrects the age of a child already "
    "mentioned ('o de 8 na verdade tem 9', 'make the younger one 6', 'the eldest is 12'): "
    "to_age is the new age; from_age the old age when they say it; which is 'younger' or "
    "'older' when that is how they point at the child ('o mais novo', 'a menor', 'the "
    "little one' = younger; 'o mais velho', 'the eldest' = older). child_ages stays empty "
    "and children stays null then: the corrected age alone is never child_ages (that "
    "would replace every other child's age) and never a date. Null otherwise.\n"
    "- child_ages: the children's ages in years when stated (a baby under one year is 0), "
    "in the order given; an empty list when not stated. 'meu filho de 5 anos' -> children 1, "
    "child_ages [5]. A reply that only gives an age ('5 anos') after a question about the "
    "child's age -> child_ages [5] with children null. A reply that gives only ages ('tem 6 "
    "anos', 'the eldest is 10 and the other 3') leaves children null: the count was given "
    "earlier.\n"
    "- people_added: ONLY people who JOIN a party that is already being planned, said as an "
    "addition ('mais', 'outro', 'também', 'another', 'also', 'joining us', 'se suma'), one "
    "entry per person, kind 'adult' (a friend, a partner, a parent, an aunt or uncle, "
    "'another adult'), 'child' (a child, a kid) or 'unsure' (a cousin, a brother or sister, "
    "a niece or nephew with no age given: the age decides) and age in years when stated, "
    "else null: 'e mais uma de 13 anos' -> [child 13]; 'também vai outra criança de 8' -> "
    "[child 8]; 'and another child aged 5' -> [child 5]; 'y otra niña de 6' -> [child 6]; "
    "'vai mais um amigo' -> [adult, no age]; 'another adult is joining us' -> [adult, no "
    "age]; 'se suma otro adulto' -> [adult, no age]; 'também vem a minha irmã de 25 anos' "
    "-> [unsure 25]; 'e meu primo vai também' -> [unsure, no age]; 'my cousin and his 5 year "
    "old are joining us' -> [unsure, no age] and [child 5]. The people in "
    "people_added are never repeated in adults, children or child_ages, which are for the "
    "whole party stated at once ('somos 3', 'são duas crianças, de 6 e 9'). An empty list "
    "when nobody joins - in particular for the first time the traveler says who is going.\n\n"
    "rooms - how many rooms they want ('dois quartos' -> 2, 'um quarto' -> 1, 'two rooms' "
    "-> 2). A number of rooms is never adults or children and says nothing about who is going: "
    "'quero dois quartos' leaves adults null. Null if not stated.\n\n"
    "confirms_party_offer - true ONLY when the assistant's previous question (shown) asked "
    "whether the people on the traveler's profile are all adults and the traveler clearly "
    "agrees ('sim', 'yes', 'isso mesmo', 'todos adultos'), even when they add something "
    "else in the same breath ('yes, and a child of 6' -> true, with the child reported "
    "separately). False in every other case, including when they give their own number of "
    "adults, disagree or say anything else.\n\n"
    "cleared_fields - only when the traveler explicitly takes a detail back or says it is "
    "no longer known/decided ('ainda não sei as datas', 'forget the dates', 'sem crianças "
    "afinal' clears children): any of 'start', 'stay', 'adults', 'children', 'child_ages', "
    "'rooms'. 'everything' ONLY when they ask to drop the whole trip and begin again "
    "('olvida todo, empecemos de nuevo', 'esquece tudo', 'start over from scratch'); "
    "never for one detail. "
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
            "stay_change": {
                "type": "object",
                "properties": {
                    "nights_delta": {"type": ["integer", "null"]},
                    "at": {"type": ["string", "null"], "enum": ["start", "end", None]},
                    "shift_days": {"type": ["integer", "null"]},
                },
                "required": ["nights_delta", "at", "shift_days"],
                "additionalProperties": False,
            },
            "adults": {"type": ["integer", "null"]},
            "children": {"type": ["integer", "null"]},
            "children_among_counted": {"type": "boolean"},
            "child_ages": {"type": "array", "items": {"type": "integer"}},
            "age_correction": {
                "type": "object",
                "properties": {
                    "from_age": {"type": ["integer", "null"]},
                    "to_age": {"type": ["integer", "null"]},
                    "which": {"type": ["string", "null"], "enum": ["younger", "older", None]},
                },
                "required": ["from_age", "to_age", "which"],
                "additionalProperties": False,
            },
            "people_added": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": ["adult", "child", "unsure"]},
                        "age": {"type": ["integer", "null"]},
                    },
                    "required": ["kind", "age"],
                    "additionalProperties": False,
                },
            },
            "rooms": {"type": ["integer", "null"]},
            "confirms_party_offer": {"type": "boolean"},
            "cleared_fields": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [
                        "start",
                        "stay",
                        "adults",
                        "children",
                        "child_ages",
                        "rooms",
                        "everything",
                    ],
                },
            },
        },
        "required": [
            "start",
            "end",
            "stay_length",
            "stay_unit",
            "stay_change",
            "adults",
            "children",
            "children_among_counted",
            "child_ages",
            "age_correction",
            "people_added",
            "rooms",
            "confirms_party_offer",
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
    quarto quartos room rooms habitacion habitaciones chambre chambres camera camere zimmer
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
    enero febrero marzo mayo junio julio septiembre setiembre octubre noviembre diciembre
    ene feb abr jun jul ago sep sept oct nov dic
    sobrino sobrina sobrinos sobrinas nieto nieta nietos nietas ahijado ahijada ahijados
    ahijadas hijastro hijastra hijastros hijastras adolescente adolescentes
    sobrinho sobrinha sobrinhos sobrinhas neto netos netas afilhado afilhada afilhados
    afilhadas enteado enteada enteados enteadas miudo miuda miudos miudas
    niece nieces nephew nephews grandson granddaughter grandchild grandchildren grandkid
    grandkids godson goddaughter godchild stepson stepdaughter stepchild stepchildren teen
    teens teenager teenagers toddler toddlers
    primo prima primos primas irmao irma irmaos irmas tio tia tios tias mae pai avo avos
    sogro sogra sogros cunhado cunhada genro nora hermano hermana hermanos hermanas abuelo
    abuela abuelos suegro suegra suegros cunado cunada yerno nuera madre padre padres
    cousin cousins brother sister brothers sisters uncle aunt uncles aunts mother father mom
    mum dad parents grandmother grandfather grandma grandpa grandparents
    amigo amiga amigos amigas colega colegas friend friends colleague colleagues coworker
    coworkers person
    menino menina meninos meninas garoto garota garotos garotas rapaz rapariga rapazes
    raparigas pequeno pequena filhote filhota chico chica nene nena chaval chavala peque
    boy girl boys girls lad lass
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
    languages, any friend, relative or child named - or a short message in which
    "one more" or "another" something comes, goes or joins, whatever it names.
    Deterministic, no model call."""
    tokens = _plain_tokens(message)
    if any(any(ch.isdigit() for ch in token) or token in _CUE_WORDS for token in tokens):
        return True
    folded = _fold(message)
    if _names_a_person(folded):
        return True
    return len(tokens) <= 10 and bool(_ADD_DETERMINER.search(folded) and _JOIN_VERB.search(folded))


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
# A niece, a grandson, a teenager: family and child words whose age the word does not
# give (she may be seven or twenty-five), so they are children only by their age.
_FAMILY_CHILD_WORDS = """
    sobrinho sobrinha sobrinhos sobrinhas neto neta netos netas afilhado afilhada afilhados
    afilhadas enteado enteada enteados enteadas miudo miuda miudos miudas adolescente
    adolescentes sobrino sobrina sobrinos sobrinas nieto nieta nietos nietas ahijado ahijada
    ahijados ahijadas hijastro hijastra hijastros hijastras niece nieces nephew nephews
    grandson granddaughter grandchild grandchildren grandkid grandkids godson goddaughter
    godchild stepson stepdaughter stepchild stepchildren teen teens teenager teenagers
    toddler toddlers
"""
_CHILDREN_WORDS = (
    """
    crianca criancas kid kids child children bebe bebes filho filha filhos filhas nino nina
    ninos ninas hijo hija hijos hijas enfant enfants fils fille bambino bambina bambini
    bambine figlio figlia kind kinder son daughter baby babies
"""
    + _FAMILY_CHILD_WORDS
)
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
    "rooms": """
        quarto quartos room rooms habitacion habitaciones chambre chambres camera camere
        zimmer
    """,
}
_CLEAR_VOCABULARY = {field: frozenset(words.split()) for field, words in _CLEAR_VOCABULARY.items()}

# Words that say who is going: the adults' vocabulary plus the family words and the
# children's. A message about ROOMS that has none of them says nothing about the
# party, so whatever count the model read into it ("dois quartos" -> 2 adults) is
# dropped.
_PEOPLE_WORDS = (
    _CLEAR_VOCABULARY["adults"]
    | _CLEAR_VOCABULARY["children"]
    | frozenset(
        """
    somos esposa esposo marido mulher namorado namorada casal amigo amiga amigos amigas
    familia sozinho sozinha wife husband partner couple friend friends family alone solo
    nous femme mari amis famille seul seule noi moglie marito amici famiglia
    """.split()
    )
)
_CHILDREN_WORD_SET = _CLEAR_VOCABULARY["children"]
_FAMILY_CHILD_SET = frozenset(_FAMILY_CHILD_WORDS.split())
# A cousin, a brother, a parent: usually grown-ups, so they are not children words - but
# "and my cousin is coming too" still says nothing about how many adults the party has.
_FAMILY_ADULT_SET = frozenset(
    """
    primo prima primos primas irmao irma irmaos irmas tio tia tios tias mae pai avo avos
    sogro sogra sogros cunhado cunhada genro nora padrinho madrinha hermano hermana hermanos
    hermanas abuelo abuela abuelos suegro suegra suegros cunado cunada yerno nuera madre
    padre padres cousin cousins brother sister brothers sisters uncle aunt uncles aunts
    mother father mom mum dad parents grandmother grandfather grandma grandpa grandparents
    """.split()
)
# "I" and "we": they say the speaker travels, not how many adults there are.
_PRONOUN_WORDS = frozenset(
    """
    eu yo i me moi io ich we us nos nosotros nosotras nous noi wir comigo conmigo
    """.split()
)
# The people words that are about the grown-ups (or the group as a whole): the
# adults' and the family vocabulary without the children's, plus "I"/"we".
_ADULT_COUNT_WORDS = _PEOPLE_WORDS - _CHILDREN_WORD_SET
_ADULT_SIDE_WORDS = _ADULT_COUNT_WORDS | _PRONOUN_WORDS
# Words that talk about an age, so that an extracted age of 0 can be believed
# (a baby, "8 meses"). A stray 0 from a message with none of them is not an age.
_AGE_WORDS = frozenset(
    """
    idade idades age ages anos ano year years edad edades ans eta alter jahre bebe bebes
    baby babies infant meses mes month months mois mesi monate recem newborn
    """.split()
)


# What a message that drops the whole trip says ("olvida todo, empecemos de
# nuevo", "esquece tudo", "start over"). Without one of these, a clear of
# "everything" is the model reading too much into a complaint.
_RESET_WORDS = frozenset(
    """
    todo tudo everything all scratch zero cero nuevo nueva novo nova new again fresh reset
    over reiniciar reiniciemos recomecar recomecemos recomencemos tout nouveau
    """.split()
)


_MONTH_WORDS = frozenset("mes meses month months mois mese mesi monat".split())
# Words that make a lone last day a return date.
_RETURN_WORDS = frozenset(
    """
    volto volta voltar voltamos voltando retorno retornamos regreso regresamos regresar
    vuelvo vuelta volvemos return returning back home checkout check until till ate hasta
    retour rentre rentrons ritorno torno zuruck heim
    """.split()
)


_RESET_GATE_WORDS = frozenset(
    """
    todo tudo everything scratch zero cero tout reset reiniciar recomecar recomecemos
    recomencemos empecemos empezar
    """.split()
)


def suggests_reset(message: str) -> bool:
    """Whether the message has a word that a "forget everything, start over" would
    have - enough to be worth the extraction call while a trip is on record.
    Narrower than the words that let the model's clear stand: "de novo" and
    "again" are in far too many ordinary messages."""
    tokens = set(_plain_tokens(message))
    return bool(tokens & _RESET_GATE_WORDS) or {"start", "over"} <= tokens


def restrict_clears(components: dict, message: str) -> dict:
    """The components with `cleared_fields` cut down to the details the message
    actually names (and "everything" to a message that really starts over)."""
    if not components["cleared_fields"]:
        return components
    tokens = set(_plain_tokens(message))
    kept = [
        f
        for f in components["cleared_fields"]
        if tokens & (_RESET_WORDS if f == "everything" else _CLEAR_VOCABULARY[f])
    ]
    return {**components, "cleared_fields": kept}


def names_detail(message: str, field: str) -> bool:
    """Whether the message names this detail ("criancas", "quartos") - the
    deterministic way to tell that a request is about it."""
    return bool(set(_plain_tokens(message)) & _CLEAR_VOCABULARY[field])


# What the Booking search link can't be told: a price level, a star rating, an
# amenity. A message that names one is asking for something Wanderes can't
# apply, and the reply has to say so rather than describe the search as being
# "for cheap hotels". Deliberately narrow (and without the plain word "price",
# which every cost question has): a miss only leaves today's behavior.
_UNSUPPORTED_FILTER_WORDS = frozenset(
    """
    barato barata baratos baratas baratinho economico economica economicos economicas
    cheap cheaper cheapest budget luxo luxuoso luxuosa luxury luxurious expensive caro
    estrela estrelas star stars estrella estrellas etoile etoiles stelle sterne
    piscina pool piscine pet pets
    """.split()
)


def names_unsupported_filter(message: str) -> bool:
    """Whether the message asks for a price level, star rating or amenity - a
    filter the search can't apply."""
    return bool(set(_plain_tokens(message)) & _UNSUPPORTED_FILTER_WORDS)


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


# Words that point at one child of several when an age is corrected ("o mais novo",
# "the eldest"); read only when an age arrives against a full set already on record.
_YOUNGER = re.compile(
    r"\b(?:younger|youngest|smaller|smallest|littlest|little one|cacula|menor"
    r"|mais\s+(?:novo|nova|novinho|novinha|jovem|pequen[oa])|mas\s+(?:pequen[oa]|joven)"
    r"|(?:o|a|el|la)\s+pequen[oa])\b"
)
_OLDER = re.compile(
    r"\b(?:older|oldest|elder|eldest|bigger|biggest|maior|mayor|mais\s+(?:velh[oa]|crescid[oa])"
    r"|mas\s+(?:grande|viej[oa])|(?:o|a|el|la)\s+grande)\b"
)
_MIDDLE = re.compile(r"\b(?:middle|do\s+meio|da\s+meio|del\s+medio|de\s+en\s+medio)\b")


# A message that is nothing but one age ("5 anos", "she's 5 years old", "he's 30"): it says how
# old, never how many.
_BARE_AGE = re.compile(
    r"^\W*(?:(?:ela|ele|she|he|it)?\s*(?:tem|tiene|has|is|es|'s)\s+\d{1,2}"
    r"(?:\s*(?:anos?|years?(?:\s+old)?|yrs?))?"
    r"|\d{1,2}\s*(?:anos?|years?(?:\s+old)?|yrs?))\W*$"
)

# What a message that adds someone to the party looks like. A count is a digit or a word.
_COUNT_WORD = (
    r"(?:\d{1,2}|um|uma|dois|duas|tres|quatro|cinco|un|uno|una|dos|cuatro"
    r"|one|two|three|four|five)"
)
# "we are 3", "somos 3", "in total": the party restated as a whole, not added to.
_TOTAL_CUE = re.compile(
    r"\b(?:somos|seremos|sao|serao|son|ficamos|vamos\s+ser|we(?:'|\s)?re|we\s+are|there\s+are)"
    rf"\s+(?:agora\s+|ahora\s+|now\s+|entao\s+)?{_COUNT_WORD}\b"
    r"|\b(?:ao\s+todo|no\s+total|em\s+total|in\s+total|in\s+all|altogether|all\s+together"
    r"|en\s+total|en\s+todo)\b"
)
# Words that say someone joins: "mais um", "outra", "another", "também", "too", "se suma".
# The definite article makes "a outra criança" the other one, not another.
_ADD_CUE = re.compile(
    rf"\b(?:mais\s+{_COUNT_WORD}"
    r"|(?<!\bo )(?<!\ba )(?<!\bos )(?<!\bas )(?<!\bel )(?<!\bla )(?<!\blos )(?<!\blas )"
    r"outr[oa]s?"
    r"|(?<!\bel )(?<!\bla )(?<!\blos )(?<!\blas )otr[oa]s?"
    r"|another|extra|additional|plus"
    rf"|{_COUNT_WORD}\s+(?:more|extra|additional)|more\s+(?:people|persons?|adults?|kids?"
    r"|children|friends?)"
    r"|(?:un|una|dos|tres)\s+(?:\w+\s+){0,2}mas"
    r"|tambem|tambien|also|too|as\s+well|joining|joins?|joined|junt\w*|incorpora\w*|chega\w*|entra\w*|integra\w*"
    r"|se\s+(?:suma|suman|une|unen|apunta|apuntan|agrega|agregan|anade|anaden)"
    r"|se\s+nos\s+(?:une|suma|agrega)|acompanha(?:r|m)?|acompana|connosco|conosco|com\s+a\s+gente"
    r"|con\s+nosotros|with\s+us|along|invit\w+|convid\w+|acrescent\w+|adicion\w+|add(?:s|ing|ed)?)\b"
)
# The strong forms of it: a determiner that makes the next person "one more".
_ADD_DETERMINER = re.compile(
    rf"\b(?:mais\s+(?:um|uma)|um\s+outr[oa]|(?<!\bo )(?<!\ba )outr[oa]|(?<!\bel )(?<!\bla )otr[oa]"
    rf"|another|plus\s+(?:an?|one|\d{{1,2}})|(?:one|{_COUNT_WORD})\s+more"
    r"|(?:un|una)\s+(?:\w+\s+){0,2}mas)\b"
)
# Verbs of coming along: with an "another" or "one more" they make a short message about someone
# joining - what opens the extraction for a message that names nobody it knows.
_JOIN_VERB = re.compile(
    r"\b(?:vai|vem|vao|vamos|viene|vienen|va|van|join\w*|coming|comes?|bring\w*|taking|takes?"
    r"|levamos|levar|leva|llevamos|llevar|trazemos|traz|traemos|suma|suman|une|unen|junt\w*"
    r"|incorpora\w*|acompanha\w*|acompana\w*|agrega\w*)\b"
)
_PERSON_NOUNS = {
    "child": re.compile(
        r"\b(?:crianca|filh(?:ot|inh)?[oa]|miud[oa]|menin[oa]|bebe|rapaz|rapariga|garot[oa]|nin[oa]"
        r"|hij[oa]"
        r"|chic[oa]|kid|child|boy|girl|baby|toddler|teen(?:ager)?|daughter|(?:my|our|his|her)\s+son"
        r"|adolescente|nen[eo]|peque|pequen[oa]|chaval|chavala|puto|puta|catraio|catraia|pibe|piba)\b"
    ),
    "adult": re.compile(
        r"\b(?:adult[oa]?|amig[oa]|friend|colega|colleague|co-?worker|pessoa|person|persona"
        r"|companheir[oa]|companer[oa]|partner|namorad[oa]|girlfriend|boyfriend|espos[oa]|wife"
        r"|husband|marido|mulher|novi[oa]|noiv[oa]|fianc\w+|prometid[oa]|roommate|flatmate)\b"
    ),
    # Relatives who are grown-ups in practice.
    "elder": re.compile(
        r"\b(?:mae|pai|avo|abuel[oa]|tio|tia|sogr[oa]|suegr[oa]|mother|father|mom|mum|dad"
        r"|grand(?:mother|father|ma|pa)|uncle|aunt|madre|padre|genro|nora|yerno|nuera"
        r"|cunhad[oa]|cunad[oa]|padrinho|madrinha)\b"
    ),
    # Relatives who may be a child or a grown-up: the age decides.
    "unsure": re.compile(
        r"\b(?:prim[oa]|cousin|irma|irmao|hermano|hermana|brother|sister|sibling|sobrinh[oa]"
        r"|sobrin[oa]|niece|nephew|net[oa]|niet[oa]|grand(?:son|daughter|child|kid)|afilhad[oa]"
        r"|ahijad[oa]|godson|goddaughter|godchild|entead[oa]|hijastr[oa]|stepson|stepdaughter"
        r"|stepchild)\b"
    ),
}
_PLURAL_PERSON = re.compile(
    r"\b(?:criancas|filhos|filhas|miudos|miudas|meninos|meninas|bebes|ninos|ninas|hijos|hijas"
    r"|kids|children|boys|girls|babies|toddlers|teens|teenagers|sons|daughters|adultos|adultas"
    r"|adults|amigos|amigas|friends|colegas|colleagues|coworkers|pessoas|people|persons"
    r"|personas|primos|primas|cousins|irmaos|irmas|hermanos|hermanas|brothers|sisters"
    r"|siblings|sobrinhos|sobrinhas|sobrinos|sobrinas|nieces|nephews|netos|netas|tios|tias"
    r"|uncles|aunts|avos|abuelos|grandparents|parents|sogros|suegros|cunhados)\b"
)
_AGE_IN = re.compile(
    r"(?<!\d)(\d{1,2})\s*-?\s*(?:anos?|years?|yrs?|y/o|ans?|jahre)\b"
    r"|\b(?:de|aged?|tem|tiene|has|is|he's|she's|com|con|of|fez|faz|completou|cumplio|cumple"
    r"|turned|turns)\s+(\d{1,2})\b"
    r"(?!\s*(?:noites?|nights?|dias?|days?|noches?|semanas?|weeks?|mes(?:es)?|months?|horas?"
    r"|hours?|quartos?|rooms?|habitaciones|adultos?|adults?|pessoas|personas|people))"
)
# Words that talk about dates or the length of the stay: a message with none of them cannot
# be moving either, whatever number the model made of an age.
_MONTH_NAMES = frozenset(
    """
    janeiro fevereiro marco abril maio junho julho agosto setembro outubro novembro dezembro
    january february march april may june july august september october november december
    enero febrero marzo mayo junio julio septiembre setiembre octubre noviembre diciembre
    ene feb abr jun jul ago sep sept oct nov dic jan aug dec
    janvier fevrier mars avril mai juin juillet aout decembre
    gennaio febbraio aprile maggio giugno luglio settembre ottobre dicembre
    januar februar marz juni juli oktober dezember
    """.split()
)
_WHEN_WORDS = (
    _CLEAR_VOCABULARY["start"]
    | _CLEAR_VOCABULARY["stay"]
    | _MONTH_WORDS
    | _MONTH_NAMES
    | frozenset("hoje amanha hoy manana today tomorrow tonight depois proximo proxima next".split())
)
_NO_CORRECTION = {"from_age": None, "to_age": None, "which": None}


def _ages_in(folded: str) -> list[int]:
    """The ages a message states, in order: a number with an age word after it ("9 anos") or
    an introducer before it ("de 9", "aged 5", "he's 25")."""
    return [int(a or b) for a, b in _AGE_IN.findall(folded)]


def _pointer_in(folded: str, known: list[int], to_age: int | None) -> tuple[int | None, str | None]:
    """Which of the children on record a message points at, from its own words: the age the
    child has now (a number that exactly one age on record has) or younger/older/middle."""
    numbers = {int(n) for n in re.findall(r"\d+", folded)}
    old = (numbers & set(known)) - {to_age}
    words = [
        name
        for name, rx in (("younger", _YOUNGER), ("older", _OLDER), ("middle", _MIDDLE))
        if rx.search(folded)
    ]
    return (next(iter(old)) if len(old) == 1 else None, words[0] if len(words) == 1 else None)


def _person_classes(folded: str) -> list[str]:
    """The kinds of person a message names, one entry per mention."""
    return [kind for kind, rx in _PERSON_NOUNS.items() for _ in rx.finditer(folded)]


_PARENTS = re.compile(
    r"\b(?:meus|minhas|nossos|nossas|mis|nuestros|nuestras|my|our)\s+(?:pais|padres)\b"
)


_COMING = frozenset("vem vai viene va vienen vao van come comes coming".split())
_NOT_COMING_TO_THE_TRIP = frozenset("de do da desde from".split())


def _says_a_person_comes(folded: str) -> bool:
    """Whether a message has someone coming next to a verb of coming ("viene mi prometida",
    "o meu pai vai", "my mother is coming"), and the traveler is not speaking of themselves
    ("eu e a minha esposa vamos...", which restates the party). A weaker cue than "also" or
    "another", for the messages that have neither."""
    tokens = re.findall(r"[a-z']+", folded)
    if set(tokens) & _PRONOUN_WORDS:
        return False
    for i, token in enumerate(tokens):
        if token not in _COMING:
            continue
        if i + 1 < len(tokens) and tokens[i + 1] in _NOT_COMING_TO_THE_TRIP:
            continue  # "vem de São Paulo": where someone is from
        if _names_a_person(" ".join(tokens[max(0, i - 4) : i + 5])):
            return True
    return False


def _names_a_person(folded: str) -> bool:
    """Whether a message names someone: a friend, a relative, a child - one or several."""
    return bool(_person_classes(folded) or _PLURAL_PERSON.search(folded) or _PARENTS.search(folded))


def _fix_kinds(added: list[dict], folded: str) -> list[dict]:
    """The words decide what a person with no age is: a friend or a mother is an adult, a
    cousin or a sister is not known to be (the age decides), a daughter is a child. Only for a
    single person: with several, which word belongs to whom is not something to guess."""
    classes = set(_person_classes(folded))
    fixed = []
    for person in added:
        kind = person["kind"]
        if len(added) == 1 and person["age"] is None and classes:
            if classes <= {"adult", "elder"}:
                kind = "adult"
            elif classes == {"unsure"}:
                kind = "unsure"
            elif classes == {"child"}:
                kind = "child"
        fixed.append({"kind": kind, "age": person["age"]})
    return fixed


def _addition_from_words(folded: str) -> dict | None:
    """The one person a short message adds to the party, from its words alone: for when the
    extraction answered with the figures of a party instead of the addition ("e mais uma
    criança de 9 anos" -> children 1, ages [9]). None unless the words clearly name exactly
    one person joining."""
    if "?" in folded or _TOTAL_CUE.search(folded) or _PLURAL_PERSON.search(folded):
        return None
    if not (_ADD_CUE.search(folded) or _says_a_person_comes(folded)):
        return None
    classes = _person_classes(folded)
    ages = _ages_in(folded)
    if len(classes) > 1 or len(ages) > 1:
        return None
    if not classes and not (ages and _ADD_DETERMINER.search(folded)):
        return None
    kind = {"elder": "adult"}.get(classes[0], classes[0]) if classes else "unsure"
    return {"kind": kind, "age": ages[0] if ages else None}


def _without_dates(components: dict) -> dict:
    """The components with every date and every length of stay taken out: "e mais uma de 13
    anos" says nothing about dates, so the 13 is not a day and not a number of nights."""
    return {
        **components,
        "start": {"day": None, "month": None, "year": None, "relative_month": None},
        "end": {"day": None, "month": None},
        "stay_length": None,
        "stay_unit": None,
        "stay_change": {"nights_delta": None, "at": None, "shift_days": None},
    }


# --- the person who joined and has no age yet ------------------------------------------------
#
# A cousin or a sister who joins with no age is held as one more child with no age, and the
# search waits. What the traveler says next about THAT person decides what they are: they are
# an adult ("ele é adulto"), they are not coming after all ("he can't come", "just the two of
# us"), or - with an age - the age path above. The words are read here, not by the model: asked
# about "he's an adult" it answers a head count of one, which would replace the adults on
# record, and "he can't come" has no cue word that opens the extraction at all.

_PENDING_BEFORE = (
    r"(?:(?:sim|yes|ok|okay|pois|entao|so|well|then|na\s+verdade|em\s+verdade|afinal|actually"
    r"|in\s+fact|claro|right|olha|mira|bueno|pues|en\s+realidad|en\s+verdad|ah|oh|ops|sorry"
    r"|desculpa|disculpa)[,.!]?\s+)*"
)
_PENDING_AFTER = (
    r"(?:[,.]?\s*(?:sim|yes|ok|okay|pois|entao|then|so|mesmo|really|already|ja|ya|claro"
    r"|of\s+course|tambem|too|afinal|after\s+all|infelizmente|unfortunately|desculpa|sorry"
    r"|obrigado|obrigada|thanks|thank\s+you|gracias|por\s+favor|please))*"
)
_RELATIVE_NOUNS = "|".join(
    sorted(
        _FAMILY_ADULT_SET
        | _FAMILY_CHILD_SET
        | frozenset(
            """
            amigo amiga friend colega colleague namorado namorada girlfriend boyfriend esposa
            esposo wife husband marido mulher novia novio noiva noivo prometida prometido
            companheiro companheira partner filho filha hijo hija son daughter
            """.split()
        ),
        key=len,
        reverse=True,
    )
)
# The one person a message speaks of: he, she, or a relative or friend by name.
_ONE_PERSON = (
    r"(?:he|she|ele|ela|el|ella"
    r"|(?:(?:my|our|the|his|her|meu|minha|nosso|nossa|o|a|mi|nuestro|nuestra|el|la)\s+){0,2}"
    rf"(?:{_RELATIVE_NOUNS}))"
)
_IS = r"(?:is|e|es)"  # he IS, ele É, él ES
_ADULT_WORD = r"(?:adult[oa]?|grown[\s-]*up|maior\s+de\s+idade|mayor\s+de\s+edad|of\s+age)"
_AN = r"(?:(?:an?|um|uma|un|una)\s+)?"
_NOT = r"(?:not|nao|no|never|nunca|ainda\s+nao|todavia\s+no|aun\s+no)\s+"

# "he's an adult", "ele é adulto", "ella es adulta": the one person is a grown-up.
_SAYS_ADULT = re.compile(
    rf"^{_PENDING_BEFORE}(?:{_ONE_PERSON}\s+(?P<before>{_NOT})?(?:already\s+|ja\s+|ya\s+)?{_IS}"
    rf"|hes|shes|(?P<bare_before>{_NOT})?(?:ja\s+|ya\s+)?{_IS})\s+(?P<after>{_NOT})?{_AN}"
    rf"{_ADULT_WORD}{_PENDING_AFTER}\W*$"
)
# Several people ("they're adults", "são adultos") or nobody in particular ("an adult").
_SAYS_ADULTS = re.compile(
    rf"^{_PENDING_BEFORE}(?:(?:they|eles|elas|ellos|ellas)\s*)?"
    rf"(?:(?:both|all|todos|todas|ambos|ambas)\s+)?(?:theyre|are|re|sao|son)\s+"
    rf"(?:(?:both|all|todos|todas|ambos|ambas)\s+)?(?:adultos?|adultas?|adults?"
    rf"|grown[\s-]*ups){_PENDING_AFTER}\W*$"
)
_SAYS_AN_ADULT = re.compile(rf"^{_PENDING_BEFORE}{_AN}adult[oa]?s?{_PENDING_AFTER}\W*$")
# With the accents folded away the Portuguese "é" (is) and "e" (and) are the same letter; "e um
# adulto" with no one to be the subject is the conjunction.
_CONJUNCTION_AND_AN = re.compile(rf"^{_PENDING_BEFORE}e\s+(?:um|uma)\b")

_NEGATIVE_EN = (
    r"(?:cant|cannot|can\s+not|couldnt|could\s+not|wont|will\s+not|isnt|is\s+not|arent"
    r"|doesnt|does\s+not|dont|do\s+not|is\s+no\s+longer|no\s+longer|not)"
)
_COMING_EN = (
    r"(?:be\s+)?(?:able\s+to\s+|going\s+to\s+|want\s+to\s+)?(?:come|coming|go|going|join|joining"
    r"|make\s+it|travel|travelling|traveling|be\s+there|come\s+along|coming\s+along"
    r"|come\s+with\s+us|coming\s+with\s+us|go\s+with\s+us|join\s+us|joining\s+us)"
)
# "he can't come", "ele não vai mais", "ya no viene": the one person is not coming after all.
_NOT_COMING = re.compile(
    rf"^{_PENDING_BEFORE}(?:"
    rf"{_ONE_PERSON}\s+(?:already\s+)?{_NEGATIVE_EN}\s+{_COMING_EN}(?:\s+any\s*more)?"
    rf"|(?:hes|shes)\s+(?:not|no\s+longer)\s+{_COMING_EN}"
    rf"|{_ONE_PERSON}\s+(?:dropped|backed|bailed|pulled)\s+out"
    rf"|{_ONE_PERSON}\s+(?:cancelled|canceled|changed\s+(?:his|her|their)\s+mind)"
    rf"|(?:hes|shes)\s+out"
    rf"|{_ONE_PERSON}\s+(?:decided|chose)\s+not\s+to\s+(?:come|go|join|travel)"
    rf"|(?:{_ONE_PERSON}\s+)?(?:ja\s+)?nao\s+(?:vai|vem|pode|podera|consegue|conseguira|ira)"
    rf"(?:\s+(?:mais|poder|ir|vir|conseguir))*"
    rf"|{_ONE_PERSON}\s+(?:desistiu|cancelou|furou|mudou\s+de\s+ideia)"
    rf"|(?:{_ONE_PERSON}\s+)?(?:ya\s+)?no\s+(?:va|viene|puede|podra|vendra|ira)"
    rf"(?:\s+(?:mas|a\s+(?:ir|venir)|ir|venir|poder))*"
    rf"|{_ONE_PERSON}\s+(?:desistio|cancelo|se\s+(?:cayo|bajo|echo\s+atras))"
    rf"){_PENDING_AFTER}\W*$"
)
# Several people, or "nobody else": whom it cancels is not for the code to say.
_NOT_COMING_MANY = re.compile(
    rf"^{_PENDING_BEFORE}(?:(?:they|eles|elas|ellos|ellas)\s+(?:{_NEGATIVE_EN}\s+{_COMING_EN}"
    rf"|(?:ja\s+)?nao\s+vao(?:\s+mais)?|(?:ya\s+)?no\s+(?:van|vienen))"
    rf"|(?:nobody|no\s+one|noone)\s+else(?:\s+(?:is\s+)?(?:coming|going|joining))?"
    rf"|ninguem\s+mais(?:\s+(?:vai|vem))?|nadie\s+mas(?:\s+(?:va|viene))?)"
    rf"{_PENDING_AFTER}\W*$"
)
_COUNT = (
    r"(?:\d{1,2}|um|uma|dois|duas|tres|quatro|cinco|seis|un|uno|una|dos|cuatro"
    r"|one|two|three|four|five|six)"
)
_COUNT_VALUES = {
    **dict.fromkeys(("um", "uma", "un", "uno", "una", "one"), 1),
    **dict.fromkeys(("dois", "duas", "dos", "two"), 2),
    **dict.fromkeys(("tres", "three"), 3),
    **dict.fromkeys(("quatro", "cuatro", "four"), 4),
    **dict.fromkeys(("cinco", "five"), 5),
    **dict.fromkeys(("seis", "six"), 6),
}
# "just the two of us", "só nós dois", "solo nosotros": the party is the people already counted.
_JUST_US = re.compile(
    rf"^{_PENDING_BEFORE}(?:its\s+|it\s+is\s+|we\s+are\s+|were\s+|so\s+|somos\s+|ficamos\s+"
    rf"|seremos\s+|entonces\s+)*(?:just|only|so|apenas|somente|solo|solamente|unicamente)\s+"
    rf"(?:the\s+(?P<a>{_COUNT})\s+of\s+us|us(?:\s+(?P<b>{_COUNT}))?"
    rf"|nos(?:\s+(?P<c>{_COUNT}))?|nosotros(?:\s+(?P<d>{_COUNT}))?|los\s+(?P<e>{_COUNT})"
    rf"|(?P<f>{_COUNT})(?:\s+of\s+us|\s+pessoas|\s+personas|\s+adultos|\s+adults)?)"
    rf"{_PENDING_AFTER}\W*$"
)

# A statement about one person is short; a longer message is read as usual.
_STATEMENT_MAX_WORDS = 12


def _pending_people(rec: dict) -> int:
    """How many people are on record as children whose age nobody has said: the relative of
    unclear kind who joined (a cousin, a sister), or a child mentioned with no age."""
    if not rec["children"]:
        return 0
    return max(rec["children"] - len(rec["child_ages"] or []), 0)


def _restates_the_party(count: int | None, rec: dict) -> bool:
    """Whether "just the two of us" names the people already counted - the adults and the
    children whose ages are known - or, with no number ("just us"), simply them."""
    counted = (rec["adults"] or 0) + len(rec["child_ages"] or [])
    return rec["adults"] is not None and (count is None or count == counted)


def _about_the_person_who_joined(folded: str) -> tuple[str, int | None] | None:
    """What a short message says about the person who just joined, from its own words:
    ("adult" | "not_adult" | "not_coming" | "just_us" | "unclear", the head count it states, if
    any) - or None when it is about anything else. The whole message has to be the statement
    (a filler word or two aside): "ele não vai mais" is a cancellation, "o hotel não vai mais
    ter vaga" is not, and a question is never one."""
    text = folded.replace("'", "").strip()
    if not text or "?" in text or len(text.split()) > _STATEMENT_MAX_WORDS:
        return None
    if _CONJUNCTION_AND_AN.match(text):
        return None  # "e um adulto" is "and an adult", not "(he) is an adult" - accents are gone
    found = _SAYS_ADULT.match(text)
    if found:
        negated = found.group("before") or found.group("bare_before") or found.group("after")
        return ("not_adult" if negated else "adult"), None
    if _NOT_COMING.match(text):
        return "not_coming", None
    if _SAYS_ADULTS.match(text) or _SAYS_AN_ADULT.match(text) or _NOT_COMING_MANY.match(text):
        return "unclear", None
    found = _JUST_US.match(text)
    if found:
        said = next((v for k, v in found.groupdict().items() if v), None)
        count = None if said is None else int(said) if said.isdigit() else _COUNT_VALUES[said]
        return "just_us", count
    return None


def _pending_verdict(statement: tuple[str, int | None] | None, rec: dict) -> str | None:
    """What a statement about the person who joined settles, given the party on record:
    "adult" (they are one more adult), "not_coming" (they are dropped), "unclear" (the traveler
    is asked) or None (nothing to settle). Only ever one pending person is settled; with none
    waiting there is nothing to settle, and with several - or no adults on record to add one
    to - which of them is meant is a question."""
    pending = _pending_people(rec)
    if statement is None or not pending:
        return None
    kind, count = statement
    if kind == "unclear":
        return "unclear"
    if kind == "just_us":
        # "Just the two of us" drops the person only when "us" is the people already counted;
        # a different number would be a new head count, and which of the two is meant is
        # a question, not a guess.
        if not _restates_the_party(count, rec):
            return "unclear"
        kind = "not_coming"
    if kind not in ("adult", "not_coming"):
        return None  # "he's not an adult" settles nothing: the age is still needed
    if pending != 1 or (kind == "adult" and rec["adults"] is None):
        return "unclear"
    return kind


def pending_person_statement(message: str, record: dict | None) -> str | None:
    """Whether the message settles, or asks about, the person who joined with no age - the
    reason to read it while the extraction would not be called. "adult", "not_coming",
    "unclear" or None."""
    rec = _normalize(record)
    if not _pending_people(rec):
        return None  # nobody is waiting: nothing to settle, and no need to read the words
    return _pending_verdict(_about_the_person_who_joined(_fold(message)), rec)


def _party_operations(
    components: dict, message: str, record: dict | None, *, figures: bool | None = None
) -> dict:
    """The incremental things a message can do to the party on record - correct the age of one
    child, add people - held to what the words say. The model reports them as components, but
    it also tends to restate the whole party beside them (`age_correction` with `child_ages`
    and `children` of one; `people_added` with `children 1, ages [9]`), and a restated party
    would replace what is on record. So:

    - a correction points at one child from the message's own words (the old age, younger,
      older, middle) and drops the age and count it was echoed in;
    - a person added needs words that say someone joins, and the figures beside them are
      dropped; when the extraction missed the addition and answered with a party's figures,
      the words rebuild it;
    - a message that restates the whole party ("somos 3") adds nobody;
    - the age given while a child waits for one is that child's age, however the model took it;
    - a statement about the person who just joined ("ele é adulto", "he can't come", "just the
      two of us") settles that one person - or is a question when it cannot - and gives no head
      count of its own, so the model's "one adult" never replaces the adults on record;
    - a message that does any of this cannot be moving the dates or the stay.

    `figures`: whether the model gave any figure for the party at all, before the guard's
    other rules dropped some of them."""
    rec = _normalize(record)
    folded = _fold(message)
    out = dict(components)
    known = list(rec["child_ages"] or [])
    dateless = not set(re.findall(r"[a-z0-9]+", folded)) & _WHEN_WORDS
    answer = _ages_in(folded) if _BARE_AGE.match(folded) else []
    if len(answer) == 1 and rec["children"] and len(known) < rec["children"]:
        # "ele tem 25 anos" right after "e meu primo vai também": the age of the person the
        # reply asked about - not somebody else joining, not a child corrected.
        out.update(
            adults=None,
            children=None,
            child_ages=answer,
            children_among_counted=False,
            people_added=[],
            age_correction=dict(_NO_CORRECTION),
        )
        return _without_dates(out) if dateless else out
    statement = _about_the_person_who_joined(folded)
    verdict = _pending_verdict(statement, rec)
    gives_no_head_count = statement is not None and (
        statement[0] in ("adult", "not_adult", "not_coming")
        or (statement[0] == "just_us" and _restates_the_party(statement[1], rec))
    )
    if verdict is not None or gives_no_head_count:
        # "ele é adulto", "he can't come", "just the two of us" (the two already counted): a
        # statement about one person, or one that repeats the party, gives no new head count, and
        # the model's "an adult" -> one adult, or "two of us" -> two adults, would replace the
        # party on record. The figures go whether or not someone is waiting, so a retry of the
        # turn (the person already settled) cannot slip them in either. What it settles is
        # decided in apply_components.
        out.update(
            adults=None,
            children=None,
            child_ages=[],
            children_among_counted=False,
            people_added=[],
            age_correction=dict(_NO_CORRECTION),
        )
        if verdict is not None:
            out["pending_person"] = verdict
        return _without_dates(out) if dateless else out
    added, unclear = _people_added(out, folded, rec, known, figures)
    if added or unclear:
        # A child's age corrected in the same message ("o mais novo tem 5 e vai mais um
        # amigo") is told apart from the new person's by the words that point at the child.
        ages = out["child_ages"]
        pointed = _pointer_in(folded, known, ages[0]) if len(ages) == 1 else (None, None)
        if pointed != (None, None) and ages[0] not in [p["age"] for p in added]:
            if out["age_correction"]["to_age"] is None:
                out["age_correction"] = {
                    "from_age": pointed[0],
                    "to_age": ages[0],
                    "which": pointed[1],
                }
        out["adults"], out["children"], out["child_ages"] = None, None, []
        out["children_among_counted"] = False
        correction = out["age_correction"]
        pointed = _pointer_in(folded, known, correction["to_age"])
        if correction["to_age"] is not None and pointed == (None, None):
            out["age_correction"] = dict(_NO_CORRECTION)  # a new child's age read as a correction
    out["people_added"] = added
    if unclear:
        out["addition_unclear"] = True
    out = _age_correction(out, folded, rec, known, additive=bool(added or unclear))
    if not (added or unclear):
        out = _one_child_or_two(out, folded, rec, known)

    if (added or unclear or out["age_correction"]["to_age"] is not None) and dateless:
        return _without_dates(out)
    return out


def _unexplained_figures(out: dict, added: list[dict], folded: str, known: list[int]) -> bool:
    """Whether the figures the model gave beside the people it reported say more than those
    people do - a child's age or a count of children none of them accounts for ("my cousin and
    his 5 year old are joining us" reported as the cousin alone). Who is joining is then not
    clear. A single age that points at a child on record is a correction, not a person."""
    ages = out["child_ages"]
    if len(ages) == 1 and _pointer_in(folded, known, ages[0]) != (None, None):
        return False
    # The count of children the model gave includes whoever it called a child, whatever the age.
    kids = [
        p
        for p in added
        if p["kind"] != "adult" or (p["age"] is not None and p["age"] <= MAX_CHILD_AGE)
    ]
    told = Counter(p["age"] for p in added if p["age"] is not None)
    too_many = out["children"] is not None and out["children"] > len(kids)
    return bool(Counter(ages) - told) or too_many


def _people_added(
    out: dict, folded: str, rec: dict, known: list[int], figures: bool | None
) -> tuple[list[dict], bool]:
    """(the people this message adds to the party on record, whether it seems to add someone
    but not clearly enough to count them)."""
    held_party = rec["adults"] is not None or bool(rec["children"])
    absolute = figures
    if absolute is None:
        absolute = (
            out["adults"] is not None or out["children"] is not None or bool(out["child_ages"])
        )
    added = [dict(person) for person in out["people_added"]]
    unclear = False
    if added:
        if not held_party and absolute:
            added = []  # the first time the party is stated: its figures are the statement
        elif _TOTAL_CUE.search(folded) or not (
            _ADD_CUE.search(folded) or _says_a_person_comes(folded)
        ):
            # The model heard someone join, but the words restate the party or don't say so
            # ("meu primo vem de São Paulo" came back as someone joining): not applied, not
            # guessed - the traveler is asked.
            added, unclear = [], True
        else:
            added = _fix_kinds(added, folded)
            if _unexplained_figures(out, added, folded, known):
                added, unclear = [], True
    elif held_party and absolute:
        person = _addition_from_words(folded)
        if person is not None:
            added = [person]
    return added, unclear


# Words that say what came before was wrong, or that the child meant is the one already counted.
_CORRECTING = re.compile(
    r"\b(?:na\s+verdade|afinal|em\s+verdade|engano|errei|erro|corrig\w+|en\s+realidad|en\s+verdad"
    r"|equivoc\w+|actually|in\s+fact|correction|i\s+meant|my\s+mistake|rather|sorry|oops"
    r"|(?:o|a|el|la|the)\s+(?:crianca|menin[oa]|miud[oa]|filh[oa]|nin[oa]|hij[oa]|child|kid|boy|girl"
    r"|son|daughter|baby|bebe))\b"
)


def _one_child_or_two(out: dict, folded: str, rec: dict, known: list[int]) -> dict:
    """One age, different from the only child's on record, with nothing to say whether it
    corrects that child or belongs to another one ("ah, e a minha filhota de 2 anos vai junto"):
    a lone figure would replace the child on record. The traveler is asked, nothing is changed.
    An age that points at the child (their old age, "ela tem 7 anos", "na verdade...") corrects."""
    ages = out["child_ages"]
    if not (
        rec["children"] == 1
        and len(known) == 1
        and len(ages) == 1
        and ages[0] != known[0]
        and out["children"] in (None, 1)
        and out["age_correction"]["to_age"] is None
    ):
        return out
    pointing = _pointer_in(folded, known, ages[0]) != (None, None)
    if (
        pointing
        or _BARE_AGE.match(folded)
        or _CORRECTING.search(folded)
        or _TOTAL_CUE.search(folded)
    ):
        return out
    return {**out, "children": None, "child_ages": [], "age_or_new_child": True}


def _age_correction(out: dict, folded: str, rec: dict, known: list[int], *, additive: bool) -> dict:
    """The correction of one child's age among the full set on record, with the child pointed
    at from the message's own words and the age (and count) it was echoed in dropped."""
    complete = bool(rec["children"]) and len(known) == rec["children"]
    if not complete:
        return out
    ages = list(out["child_ages"])
    correction = dict(out["age_correction"])
    absolute = out["adults"] is not None or out["children"] is not None or bool(ages)
    if correction["to_age"] is None and not additive:
        few = out["children"] in (None, 1, rec["children"])
        if len(ages) == 1 and rec["children"] >= 2 and few:
            # One age against a full set of ages can only be a correction of one of those
            # children, never a new set: "o de 8 na verdade tem 9", "make the younger one 6".
            correction = {**_NO_CORRECTION, "to_age": ages[0]}
            ages = []
        elif not absolute and not out["people_added"]:
            # The model found nothing in "o do meio tem 8 na verdade": a short message that
            # points at a child with younger/older/middle and gives one age says what it says.
            found = _ages_in(folded)
            _, which = _pointer_in(folded, known, found[0]) if len(found) == 1 else (None, None)
            short = len(folded.split()) <= 10 and "?" not in folded
            others = _person_classes(folded) or _PLURAL_PERSON.search(folded)
            if which and short and not others:
                correction = {**_NO_CORRECTION, "to_age": found[0]}
    if correction["to_age"] is not None and ages in ([], [correction["to_age"]]):
        from_age, which = _pointer_in(folded, known, correction["to_age"])
        said = correction["from_age"]
        if from_age is None and said not in (None, correction["to_age"]):
            # An old age the model read out of the message - but only one the message has
            # (the new age repeated as the old one points nowhere).
            from_age = said if str(said) in re.findall(r"\d+", folded) else None
        # The model's own `which` is not used: with no word in the message that points at a child
        # it is a guess ("uma delas tem 8" came back as "the younger one").
        if from_age is None and which is None and correction["to_age"] in known:
            # An age one of the children already has, with nothing pointing anywhere else
            # ("tem 8 anos" again): said twice, not a change.
            correction = dict(_NO_CORRECTION)
        else:
            correction = {"from_age": from_age, "to_age": correction["to_age"], "which": which}
        ages = []
        if out["children"] in (None, 1, rec["children"]):
            out["children"] = None
    return {**out, "child_ages": ages, "age_correction": correction}


# --- how many rooms the words ask for ---------------------------------------------------------

# Words for a room. Wider than the vocabulary that marks a message as being about rooms
# (_CLEAR_VOCABULARY["rooms"]): there a word must mean a room wherever it appears, here it only
# counts when a number stands right next to it, so "cuarto" (a room, but also a fourth) is safe.
_ROOM_NOUNS = _CLEAR_VOCABULARY["rooms"] | frozenset(
    "bedroom bedrooms suite suites cuarto cuartos dormitorio dormitorios stanza stanze".split()
)
_ROOM_COUNT_VALUES = {
    **dict.fromkeys(("um", "uma", "un", "uno", "una", "one", "une", "ein", "eine", "a", "an"), 1),
    **dict.fromkeys(("dois", "duas", "dos", "two", "deux", "due", "zwei"), 2),
    **dict.fromkeys(("tres", "three", "trois", "tre", "drei"), 3),
    **dict.fromkeys(("quatro", "cuatro", "four", "quatre", "quattro", "vier"), 4),
    **dict.fromkeys(("cinco", "five", "cinq", "cinque", "funf"), 5),
    **dict.fromkeys(("seis", "six", "sei", "sechs"), 6),
    **dict.fromkeys(("sete", "siete", "seven", "sept", "sette", "sieben"), 7),
    **dict.fromkeys(("oito", "ocho", "eight", "huit", "otto", "acht"), 8),
    **dict.fromkeys(("nove", "nueve", "nine", "neuf", "neun"), 9),
    **dict.fromkeys(("dez", "diez", "ten", "dix", "dieci", "zehn"), 10),
}
# Words that end the search for the number in front of a room word: whoever the number counts,
# it is not the rooms ("2 adultos quartos separados"), and neither is a number across a "de".
_NOT_A_DESCRIPTION_OF_A_ROOM = _PEOPLE_WORDS | frozenset(
    "e y and et und ou or de do da das para for with com con em en in at no na".split()
)


def _count_in(word: str) -> int | None:
    if word.isdigit() and len(word) <= 2:
        return int(word)
    if word.endswith("x") and word[:-1].isdigit() and len(word) <= 3:  # "2x"
        return int(word[:-1])
    return _ROOM_COUNT_VALUES.get(word)


def _rooms_stated(message: str) -> list[int]:
    """The numbers of rooms a message states: a number, or "um"/"a", right before a word for a
    room with at most two describing words between ("dois quartos", "two double rooms", "2x
    habitaciones"), or after one behind a colon ("quartos: 2"). Punctuation ends the search, so
    "2 adultos, quartos separados" states no number of rooms."""
    words = re.findall(r"[a-z0-9]+|[^\sa-z0-9]", _fold(message))
    stated: list[int] = []
    for i, word in enumerate(words):
        if word not in _ROOM_NOUNS and not word.endswith("zimmer"):
            continue
        j, between = i - 1, 0
        while j >= 0 and between <= 2:
            before = words[j]
            count = _count_in(before)
            if count is not None:
                stated.append(count)
                break
            if not before.isalpha() or before in _NOT_A_DESCRIPTION_OF_A_ROOM:
                break
            j, between = j - 1, between + 1
        if i + 2 < len(words) and words[i + 1] in (":", "=", "x"):
            count = _count_in(words[i + 2])
            if count is not None:
                stated.append(count)
    return stated


def guard_components(components: dict, message: str, record: dict | None = None) -> dict:
    """What the extraction found, held to what the message says: a clear only
    for the detail it names (restrict_clears); "next month" only from a message
    that says month; a last day alone only as a return date; a message about
    rooms or about a child that says nothing about the adults cannot change the
    adults; a number of rooms only when the words state it; an age of 0 only from a message
    that talks about an age; and what a message does to the party on `record` - correct one
    child's age, add people - is read from its words (`_party_operations`)."""
    components = restrict_clears(components, message)
    figures = (
        components["adults"] is not None
        or components["children"] is not None
        or bool(components["child_ages"])
    )
    tokens = set(_plain_tokens(message))
    out = dict(components)
    if out["start"]["relative_month"] is not None and not tokens & _MONTH_WORDS:
        # The model sometimes adds "next" to a month it was simply told ("from
        # Dec 20"), which would move the trip to the month after today.
        out["start"] = {**out["start"], "relative_month": None}
    if out["end"]["day"] is not None and out["start"]["day"] is None and not tokens & _RETURN_WORDS:
        # "volto dia 20" is a return date; "o de 8 na verdade tem 9" is not a
        # last day, whatever the model made of the 9.
        out["end"] = {"day": None, "month": None}
    if out["rooms"] is not None:
        # Adults and rooms are separate numbers: "dois adultos" is two adults, never two rooms,
        # and a room is never counted per adult or out of a request for somewhere to stay. The
        # model has read the first as the second now and then; the number of rooms is what the
        # words say, or nothing - so the one on record stays as it is.
        stated = _rooms_stated(message)
        if out["rooms"] not in {*stated, sum(stated) if len(stated) > 1 else None}:
            out["rooms"] = None
    if tokens & _CLEAR_VOCABULARY["rooms"] and not tokens & _PEOPLE_WORDS:
        out["adults"] = None
        out["children"] = None
        out["child_ages"] = []
    elif tokens & _CHILDREN_WORD_SET and not tokens & _ADULT_SIDE_WORDS:
        # "e meu filho de 15 anos" / "yes, and a child of 6" talk about a child
        # and say nothing about the adults: the model's "1 adult" is the
        # traveler counted by default, which must not replace who was said to
        # be going.
        out["adults"] = None
    elif tokens & _FAMILY_CHILD_SET and not tokens & _ADULT_COUNT_WORDS:
        # The same for a niece or a grandson, with "I"/"we" allowed: "and we're
        # bringing my niece, she's 7" joins someone to the party and says nothing
        # about how many adults it has.
        out["adults"] = None
    held_adults = _normalize(record)["adults"]
    if (
        held_adults is not None
        and out["adults"] is not None
        and out["adults"] < held_adults
        and tokens & _FAMILY_ADULT_SET
        and not tokens & (_ADULT_COUNT_WORDS | _PRONOUN_WORDS)
    ):
        # "e minha prima vai também": the model counted the traveler and the cousin and
        # nobody else, which is not a statement that the party shrank.
        out["adults"] = None
    if 0 in out["child_ages"] and not tokens & _AGE_WORDS:
        out["child_ages"] = [a for a in out["child_ages"] if a != 0]
    if out["child_ages"] and _BARE_AGE.match(_fold(message)):
        # The model reads "5 anos" as one child, now and then; a count it read into an age
        # cannot add, remove or replace anyone.
        out["children"] = None
        out["adults"] = None
    out = _party_operations(out, message, record, figures=figures)
    if out.get("children_among_counted") and not tokens & _PARTITIVE_WORDS:
        # Only a message that says "of them / of us" reclassifies people already counted.
        out["children_among_counted"] = False
    grown = _grown_child_age(message)
    correcting = (out.get("age_correction") or {}).get("to_age") is not None
    open_question = out.get("age_or_new_child") or out.get("addition_unclear")
    if (
        grown is not None
        and not out["child_ages"]
        and not correcting
        and not out["people_added"]
        and not open_question
    ):
        # "nosso filho de 19 anos": the model leaves the 19-year-old out half the time.
        # Reported as a child with that age, the rules turn him into an adult.
        out["children"] = out["children"] or 1
        out["child_ages"] = [grown]
    return out


# Words that make "N are children" a statement about people already counted.
_PARTITIVE_WORDS = frozenset(
    "deles delas ellos ellas them us nosotros nosotras among entre dentre dont cui".split()
)
_CHILD_NOUN = (
    r"(?:filh[oa]s?|hij[oa]s?|(?:my|our)\s+son|daughter|ni[nñ][oa]s?|kids?|child|crianca|enfant"
    r"|fils|fille|figli[oa]|bambin[oa]|sohn|tochter"
    r"|sobrinh[oa]s?|sobrin[oa]s?|net[oa]s?|niet[oa]s?|afilhad[oa]s?|ahijad[oa]s?"
    r"|entead[oa]s?|hijastr[oa]s?|nieces?|nephews?|grand(?:son|daughter|child|kid)s?"
    r"|godson|goddaughter|godchild|stepson|stepdaughter|stepchild)"
)
_ENGLISH_CHILD = (
    r"(?:son|daughter|kid|child|boy|girl|nieces?|nephews?|grand(?:son|daughter|child|kid)"
    r"|godson|goddaughter|godchild|stepson|stepdaughter|stepchild)"
)
_AGE_UNIT = r"(?:anos?|years?|yrs?|ans?|anni|jahre)"
_GROWN_AFTER_NOUN = re.compile(
    rf"\b{_CHILD_NOUN}\b[^.;\d]{{0,12}}?\b(1[89]|[2-9]\d)\s*{_AGE_UNIT}\b"
)
_GROWN_BEFORE_NOUN = re.compile(
    rf"\b(1[89]|[2-9]\d)[\s-]*{_AGE_UNIT}[\s-]*old\s+{_ENGLISH_CHILD}\b"
)


def _grown_child_age(message: str) -> int | None:
    """An age of 18 or more that the message ties to a son, daughter or child
    ("nosso filho de 19 anos", "my 20 year old son"); the traveler's own age or
    anyone else's is not tied to one."""
    folded = unicodedata.normalize("NFKD", message).encode("ascii", "ignore").decode().lower()
    found = _GROWN_AFTER_NOUN.search(folded) or _GROWN_BEFORE_NOUN.search(folded)
    return int(found.group(1)) if found else None


_NUMBER_WORDS = frozenset(
    """
    um uma dois duas tres quatro cinco seis sete oito nove dez
    uno una dos cuatro ocho diez
    one two three four five six seven eight nine ten
    un deux trois quatre cinq huit dix
    """.split()
)

# What a short "sim" is answering while the question about the profile's party
# is pending. The system knows exactly what it asked, so the model is told that
# rather than shown the reply - whose wording ("mais duas pessoas") it could
# read a head count out of.
PARTY_OFFER_QUESTION = (
    "Whether the people on the traveler's profile are all adults (the number of people "
    "is not shown to you)."
)


def _mask_numbers(text: str) -> str:
    """The text with every number, written in digits or spelled out, replaced by
    '#'."""

    def fold(word: str) -> str:
        return unicodedata.normalize("NFKD", word).encode("ascii", "ignore").decode().lower()

    def mask_word(match: re.Match) -> str:
        return "#" if fold(match.group()) in _NUMBER_WORDS else match.group()

    return re.sub(r"[^\W\d_]+", mask_word, re.sub(r"\d+", "#", text))


def previous_question_for_extraction(
    history: list[dict] | None, message: str, *, party_offer_pending: bool = False
) -> str | None:
    """The assistant's last message, trimmed, for a short reply that needs it
    ('5 anos' answers a question); None for a message that stands alone - and
    for a last message that asked nothing, which a reply has nothing to answer
    in. Every number in it is masked so one the assistant itself said can't be
    read as something the traveler said."""
    if len(_plain_tokens(message)) > 8:
        return None
    for turn in reversed(history or []):
        if turn.get("role") == "assistant":
            if party_offer_pending:
                return PARTY_OFFER_QUESTION
            content = str(turn.get("content", ""))
            if "?" not in content:
                return None
            return _mask_numbers(content)[-400:] or None
    return None


def awaiting_occupancy(record: dict | None) -> bool:
    """True while a trip has its when or how long but nobody has said who is
    going - the state in which a short reply with no cue word in it ("sou só
    eu", "me and my brother") is most likely the answer to the question just
    asked."""
    rec = _normalize(record)
    return rec["adults"] is None and bool(rec["start_date"] or rec["stay_length"])


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
        if f in ("start", "stay", "adults", "children", "child_ages", "rooms", "everything")
    ]
    change = raw.get("stay_change") if isinstance(raw.get("stay_change"), dict) else {}
    correction = raw.get("age_correction") if isinstance(raw.get("age_correction"), dict) else {}
    joined = raw.get("people_added") if isinstance(raw.get("people_added"), list) else []
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
        # A change relative to the stay on record; zero is no change at all.
        "stay_change": {
            "nights_delta": _int_in(change.get("nights_delta"), -MAX_STAY_LENGTH, MAX_STAY_LENGTH)
            or None,
            "at": change.get("at") if change.get("at") in ("start", "end") else None,
            "shift_days": _int_in(change.get("shift_days"), -MAX_STAY_LENGTH, MAX_STAY_LENGTH)
            or None,
        },
        "adults": _int_in(raw.get("adults"), 1, MAX_ADULTS),
        "children": _int_in(raw.get("children"), 0, MAX_CHILDREN),
        "children_among_counted": raw.get("children_among_counted") is True,
        "child_ages": ages,
        "age_correction": {
            "from_age": _int_in(correction.get("from_age"), 0, 120),
            "to_age": _int_in(correction.get("to_age"), 0, 120),
            "which": correction.get("which")
            if correction.get("which") in ("younger", "older")
            else None,
        },
        # People who join the party, one entry each; a kind the code doesn't know is dropped.
        "people_added": [
            {"kind": person["kind"], "age": _int_in(person.get("age"), 0, 120)}
            for person in joined[:MAX_PEOPLE_ADDED]
            if isinstance(person, dict) and person.get("kind") in ("adult", "child", "unsure")
        ],
        "rooms": _int_in(raw.get("rooms"), 1, MAX_ROOMS),
        "confirms_party_offer": raw.get("confirms_party_offer") is True,
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
    out["rooms"] = _int_in(record.get("rooms"), 1, MAX_ROOMS)
    out["adults_offer"] = _int_in(record.get("adults_offer"), 1, MAX_ADULTS)
    out["delta_turn"] = _int_in(record.get("delta_turn"), 0, 10**9)
    out["party_turn"] = _int_in(record.get("party_turn"), 0, 10**9)
    if out["start_date"] is None:  # a month alone only counts while there is no full date
        out["start_month"] = _int_in(record.get("start_month"), 1, 12)
        if out["start_month"]:
            out["start_year"] = _int_in(record.get("start_year"), 2000, 2200)
    children = _int_in(record.get("children"), 0, MAX_CHILDREN)
    out["children"] = children
    ages = record.get("child_ages")
    if children and isinstance(ages, list):
        kept = [a for a in ages if _int_in(a, 0, MAX_CHILD_AGE) is not None]
        if kept and len(kept) <= children:
            out["child_ages"] = kept
    return out


def with_party_offer(record: dict | None, count: int) -> dict:
    """The stored record with the profile's party size noted as the question
    just asked - what the traveler's next "sim" is read against."""
    rec = _normalize(record)
    rec["adults_offer"] = _int_in(count, 1, MAX_ADULTS)
    return rec


def _stored(record: dict) -> dict | None:
    """The record to persist: None when nothing is known. Optional keys that are
    empty (a lapsed offer, no partial month) are simply absent, so a record with
    none of them looks as it always did. A record that holds only the bookkeeping
    of an earlier relative change holds nothing."""
    if {**record, "delta_turn": None, "party_turn": None} == EMPTY_RECORD:
        return None
    return {k: v for k, v in record.items() if k not in _OPTIONAL_KEYS or v is not None}


@dataclass(frozen=True)
class Issue:
    """Something the traveler said that couldn't be used; the reply asks."""

    # "start_in_past" | "invalid_date" | "end_not_after_start" | "relative_without_length" |
    # "relative_without_start" | "ambiguous_shift" | "invalid_stay_change" |
    # "ambiguous_age_correction" | "party_conflict" | "addition_without_party" |
    # "addition_unclear" | "party_too_large" | "age_or_new_child" | "pending_person_unclear"
    code: str
    when: date | None = None
    n: int | None = None  # a number the question is about (the nights a change would leave)


@dataclass(frozen=True)
class Applied:
    record: dict | None
    changed: bool
    issues: tuple[Issue, ...] = ()
    # The traveler just told us about a child without an age: ask for it, once.
    ask_child_ages: bool = False
    # This message set or changed the number of rooms.
    rooms_changed: bool = False
    # Something the search is built from changed - not just an offer that lapsed.
    details_changed: bool = False
    # The traveler dropped the whole trip and began again.
    reset: bool = False
    # Someone joined whose age is not known and whose kind is not clear (a cousin, a sister).
    pending_relative: bool = False
    # The traveler settled that person without an age: "adult" (one more adult) or
    # "not_coming" (dropped).
    pending_resolved: str | None = None


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


def _partial_month(start: dict, today: date) -> tuple[int | None, int | None]:
    """(month, year) of a month named with no day: "em janeiro" is (1, None), "mês que
    vem" the month after today and its year. (None, None) when no month is named."""
    if start["relative_month"] == "this":
        return today.month, today.year
    if start["relative_month"] == "next":
        year, month = _next_month(today.year, today.month)
        return month, year
    if start["month"] is not None:
        return start["month"], start["year"]
    return None, None


def _which_child(known: list[int], correction: dict) -> tuple[int | None, Issue | None]:
    """The index of the child whose age is being corrected, from what the traveler said about
    them (the old age, or younger/older/middle). Only a child that is the one and only match
    is found; when nothing says which, or two children fit (twins, the same age), ask."""
    ask = Issue("ambiguous_age_correction")
    if correction["from_age"] is not None:
        hits = [i for i, age in enumerate(known) if age == correction["from_age"]]
    elif correction["which"] in ("younger", "older"):
        edge = min(known) if correction["which"] == "younger" else max(known)
        hits = [i for i, age in enumerate(known) if age == edge]
    elif correction["which"] == "middle":
        # Only a set of three has a middle one.
        middle = sorted(known)[1] if len(known) == 3 else None
        hits = [i for i, age in enumerate(known) if age == middle]
    elif len(known) == 1:
        hits = [0]
    else:
        hits = []
    return (hits[0], None) if len(hits) == 1 else (None, ask)


def _apply_stay_change(rec: dict, change: dict, today: date, turn: int | None) -> Issue | None:
    """A change relative to the stay on record: "add a night" lengthens it,
    "remove a night" shortens it, "at the start" also moves the start. Whatever
    can't be done without guessing (no length on record, no start date for a
    change at the start, a length that would be nothing, dates that shift without
    saying what happens to the check-out) is returned as a question and changes
    nothing. A change already applied on this very turn (a retry) is not applied
    again."""
    if turn is not None and rec["delta_turn"] == turn:
        return None
    delta, at = change["nights_delta"], change["at"]
    if delta is None:
        return Issue("ambiguous_shift", n=change["shift_days"])
    if rec["stay_length"] is None:
        return Issue("relative_without_length", n=delta)
    new_length = rec["stay_length"] + delta
    if not 1 <= new_length <= MAX_STAY_LENGTH:
        return Issue("invalid_stay_change", n=new_length)
    if at == "start":
        start = _parse_iso(rec["start_date"])
        if start is None:
            return Issue("relative_without_start", n=delta)
        new_start = start - timedelta(days=delta)
        if new_start < today:
            return Issue("start_in_past", new_start)
        rec["start_date"] = new_start.isoformat()
    rec["stay_length"] = new_length
    if turn is not None:
        rec["delta_turn"] = turn
    return None


def _apply_people_added(
    rec: dict, added: list[dict], already_done: bool
) -> tuple[bool, Issue | None, bool]:
    """People who join the party on record are added to it: an adult (or anyone 18 or over) to
    the adults, a child to the children with the age when it is known. Nobody on record is
    replaced, and a relative whose kind isn't clear and has no age is a child with no age until
    the traveler says how old they are - the search waits, the reply asks. What can't be added
    (no party yet to add to, a party that would be too large) is returned as a question and
    changes nothing. People already added on this very turn (a retry) are not added again.
    Returns whether anyone was added, the question when they could not be, and whether someone
    of a kind that is not clear was added with no age."""
    if not added or already_done:
        return False, None, False
    adults, ages, unknown = 0, [], 0
    for person in added:
        age = person["age"]
        grown = age > MAX_CHILD_AGE if age is not None else person["kind"] == "adult"
        if grown:
            adults += 1
        elif age is not None:
            ages.append(age)
        else:
            unknown += 1
    children = len(ages) + unknown
    if rec["adults"] is None and (adults or not rec["children"]):
        return False, Issue("addition_without_party"), False
    total_adults = (rec["adults"] or 0) + adults
    total_children = (rec["children"] or 0) + children
    if total_adults > MAX_ADULTS or total_children > MAX_CHILDREN:
        return False, Issue("party_too_large"), False
    if adults:
        rec["adults"] = total_adults
    if children:
        rec["children"] = total_children
        rec["child_ages"] = [*(rec["child_ages"] or []), *ages] or None
    unclear_kind = any(p["age"] is None and p["kind"] == "unsure" for p in added)
    return True, None, unclear_kind


def _resolve_pending_person(rec: dict, verdict: str) -> tuple[str | None, Issue | None]:
    """The one person waiting for an age is settled by what the traveler said about them:
    "adult" makes them one more adult, "not_coming" drops them. Nobody else on record is touched
    - the adults and the ages already known stay as they are. Anything the code cannot settle
    without guessing (no one waiting, several waiting, no adults on record to add one to, a
    party that would be too large) is returned as a question and changes nothing. Settling
    someone removes them from the waiting, so the same turn run twice settles nobody else."""
    pending = _pending_people(rec)
    if verdict == "unclear" or pending != 1 or (verdict == "adult" and rec["adults"] is None):
        return None, Issue("pending_person_unclear")
    if verdict == "adult" and rec["adults"] >= MAX_ADULTS:
        return None, Issue("party_too_large")
    rec["children"] -= 1
    if verdict == "adult":
        rec["adults"] += 1
    if not rec["children"]:
        rec["child_ages"] = None
    return verdict, None


def apply_components(
    current: dict | None, components: dict, today: date, *, turn: int | None = None
) -> Applied:
    """Fold what the traveler just said into the stored record. A new value
    replaces the old one (that is what a correction is), an explicit clear
    drops it, anything not mentioned stays as it was. Derived values are never
    stored, so a corrected start date or length simply moves the check-out.
    `turn` numbers the traveler's messages in the conversation: it is what keeps
    a relative change from being applied twice when the same turn runs twice."""
    before = _normalize(current)
    rec = dict(before)
    issues: list[Issue] = []
    party_done = turn is not None and before["party_turn"] == turn
    party_changed = False

    reset = "everything" in components["cleared_fields"]
    if reset:
        rec = dict(EMPTY_RECORD)
    for field_name in components["cleared_fields"]:
        if field_name == "start":
            rec["start_date"], rec["start_assumed_month"] = None, False
            rec["start_month"], rec["start_year"] = None, None
        elif field_name == "stay":
            rec["stay_length"], rec["stay_unit"] = None, None
        elif field_name == "adults":
            rec["adults"] = None
        elif field_name == "children":
            rec["children"], rec["child_ages"] = None, None
        elif field_name == "child_ages":
            rec["child_ages"] = None
        elif field_name == "rooms":
            rec["rooms"] = None

    start = components["start"]
    start_date = None
    if start["day"] is not None and start["month"] is None and start["relative_month"] is None:
        # A bare day completes the month the traveler named earlier ("em janeiro", then "dia 10").
        if rec["start_month"] is not None:
            year = start["year"] or rec["start_year"]
            start = {**start, "month": rec["start_month"], "year": year}
    if start["day"] is None:
        month, year = _partial_month(start, today)
        if month is not None:
            if year is not None and (year, month) < (today.year, today.month):
                issues.append(Issue("month_in_past", date(year, month, 1)))
            else:
                held = _parse_iso(rec["start_date"])
                same_month = held is not None and held.month == month and year in (None, held.year)
                if not same_month:
                    # A month alone is all the traveler knows now: the day on record, if
                    # any, was for another month, and no day or year is made up.
                    rec["start_date"], rec["start_assumed_month"] = None, False
                    rec["start_month"], rec["start_year"] = month, year
    elif any(v is not None for v in start.values()):
        start_date, assumed, issue = _resolve_start(
            start,
            today,
            prior=_parse_iso(before["start_date"]),
            prior_assumed=before["start_assumed_month"],
        )
        if issue is not None:
            issues.append(issue)
        elif start_date is not None:
            rec["start_date"] = start_date.isoformat()
            rec["start_assumed_month"] = assumed
            rec["start_month"], rec["start_year"] = None, None

    change = components.get("stay_change") or {}
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
    elif change.get("nights_delta") or change.get("shift_days"):
        issue = _apply_stay_change(rec, change, today, turn)
        if issue is not None:
            issues.append(issue)

    if components["adults"] is not None:
        rec["adults"] = components["adults"]
    if components["rooms"] is not None:
        rec["rooms"] = components["rooms"]
    ages = list(components["child_ages"])
    children = components["children"]
    correction = components.get("age_correction") or {}
    if correction.get("to_age") is not None:
        known = list(rec["child_ages"] or [])
        complete = bool(rec["children"]) and len(known) == rec["children"]
        if (complete or party_done) and ages in ([], [correction["to_age"]]):
            # The model often repeats the corrected age as `child_ages`, with a count of one,
            # beside the correction; neither is a new set of children.
            ages = []
            if children in (None, 1, rec["children"]):
                children = None
            if not party_done:
                index, issue = _which_child(known, {"from_age": None, "which": None, **correction})
                if issue is not None:
                    issues.append(issue)
                else:
                    # One age changes; the other children keep theirs.
                    party_changed = known[index] != correction["to_age"]
                    known[index] = correction["to_age"]
                    ages, children = known, len(known)
        elif not ages:
            ages = [correction["to_age"]]  # no full set to correct: it is just an age
    if components.get("children_among_counted") and children and components["adults"] is None:
        # "Two of them are children": the people already counted are reclassified,
        # not joined by two more.
        counted = (rec["adults"] or 0) + (rec["children"] or 0)
        if rec["adults"] is not None and children < counted:
            rec["adults"] = counted - children
            known = list(rec["child_ages"] or [])
            rec["children"] = children
            rec["child_ages"] = known if known and len(known) <= children else None
            children = None
        elif counted:
            issues.append(Issue("party_conflict", n=counted))
            children = None
    if children is not None and ages and before["children"] and children == len(ages):
        if children < before["children"]:
            # Some ages of a bigger group ("a de 5 anos"), not a smaller party:
            # never let an answer about ages quietly drop a child we know of.
            children = None
    held = list(rec["child_ages"] or [])
    if (
        ages
        and rec["children"]
        and len(held) == rec["children"]
        and len(ages) < rec["children"]
        and children in (None, rec["children"])
    ):
        # Fewer ages than children while every child's age is already known: they
        # correct some of those children, but which is not known. Never a new set -
        # it would replace the ages of the children they say nothing about.
        issues.append(Issue("ambiguous_age_correction"))
        ages, children = [], None
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

    # A "yes" to the question about the profile's party only counts while that
    # question is the one being answered, and anything they say about adults wins.
    offered = before["adults_offer"]
    if (
        offered
        and components.get("confirms_party_offer")
        and components["adults"] is None
        and "adults" not in components["cleared_fields"]
    ):
        rec["adults"] = offered
    rec["adults_offer"] = None  # good for the one reply it was made for

    pending_resolved = None
    if components.get("pending_person") and not party_done:
        pending_resolved, issue = _resolve_pending_person(rec, components["pending_person"])
        if issue is not None:
            issues.append(issue)
    added, issue, pending_relative = _apply_people_added(
        rec, components.get("people_added") or [], party_done
    )
    if issue is not None:
        issues.append(issue)
    elif components.get("addition_unclear"):
        issues.append(Issue("addition_unclear"))
    if components.get("age_or_new_child"):
        issues.append(Issue("age_or_new_child"))
    if turn is not None and (party_changed or added):
        rec["party_turn"] = turn

    rec = _normalize(rec)
    # Ask when this message moved the children's details forward without
    # completing them: a child mentioned with no age, or some ages of several.
    ask = (
        bool(rec["children"])
        and len(rec["child_ages"] or []) != rec["children"]
        and (rec["children"] != before["children"] or rec["child_ages"] != before["child_ages"])
    )

    def details(record: dict) -> dict:
        bookkeeping = ("adults_offer", "delta_turn", "party_turn")
        return {k: v for k, v in record.items() if k not in bookkeeping}

    return Applied(
        _stored(rec),
        rec != before,
        tuple(issues),
        ask,
        rooms_changed=rec["rooms"] != before["rooms"],
        details_changed=details(rec) != details(before),
        reset=reset,
        pending_relative=pending_relative,
        pending_resolved=pending_resolved,
    )


# --- the single resolved view -----------------------------------------------


@dataclass(frozen=True)
class ResolvedTrip:
    """What is known about the trip right now, as one object. The URL, the
    caption and the reply's facts are all read from this."""

    start_date: date | None = None  # a usable start, with or without a length yet
    check_in: date | None = None
    check_out: date | None = None
    nights: int | None = None
    start_assumed_month: bool = False
    stay_length: int | None = None
    stay_unit: str | None = None
    adults: int | None = None
    children: int | None = None
    child_ages: tuple[int, ...] = ()
    rooms: int | None = None
    # Why a known detail isn't in the search.
    start_date_past: bool = False
    # A month the traveler named with no day yet: partial information, never dates.
    start_month: int | None = None
    start_month_year: int | None = None

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
    def rooms_in_search(self) -> bool:
        """Booking silently clamps the rooms to the number of adults, so a room
        count is only sent - and only claimed - when it fits."""
        return self.rooms is not None and self.adults is not None and self.rooms <= self.adults

    @property
    def rooms_conflict(self) -> bool:
        """More rooms asked for than adults: not representable in the search."""
        return self.rooms is not None and self.adults is not None and self.rooms > self.adults

    @property
    def is_informative(self) -> bool:
        return (
            self.has_dates
            or self.stay_length is not None
            or self.adults is not None
            or bool(self.children)
            or self.rooms is not None
            or self.start_date_past
            or self.start_month is not None
        )

    @property
    def missing_for_search(self) -> tuple[str, ...]:
        """What the Booking search still needs, in the order to ask for it:
        the start date, the length of the stay, who is going, the children's
        ages, a room count that fits. Empty when the search is ready. This is
        the one readiness decision - the card, the reply and the buttons already
        on the page all follow it."""
        missing = []
        if self.start_date is None:
            missing.append("check_in")
        if self.stay_length is None:
            missing.append("stay_length")
        if self.adults is None:
            missing.append("adults")
        if self.children_pending:
            missing.append("child_ages")
        if self.rooms_conflict:
            missing.append("rooms")
        return tuple(missing)

    @property
    def search_ready(self) -> bool:
        return not self.missing_for_search

    def search_kwargs(self) -> dict | None:
        """What the search carries, or None while it isn't ready: then there is
        no search to link to at all, not a smaller one."""
        return self.booking_kwargs() if self.search_ready else None

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
            if self.rooms_in_search:
                kwargs["rooms"] = self.rooms
        return kwargs

    def link_summary(self) -> dict:
        """What the search link carries, as plain values - for the diagnostic
        record of a click. Only these operational details; never the URL."""
        kwargs = self.booking_kwargs()
        return {
            "check_in": kwargs["check_in"].isoformat() if "check_in" in kwargs else None,
            "check_out": kwargs["check_out"].isoformat() if "check_out" in kwargs else None,
            "adults": kwargs.get("adults"),
            "children": kwargs.get("children"),
            "child_ages": kwargs.get("child_ages", []),
            "rooms": kwargs.get("rooms"),
        }

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

    def _rooms_text(self) -> str | None:
        if self.rooms is None:
            return None
        count = ngettext("%(n)d room", "%(n)d rooms", self.rooms) % {"n": self.rooms}
        if self.rooms_in_search:
            return count
        if self.adults is None:
            return _("%(count)s not included yet - the number of adults is needed") % {
                "count": count
            }
        return _("%(count)s not included - Booking needs an adult in every room") % {"count": count}

    def caption(self, place: str) -> str:
        """The line shown under the "Search stays" button: exactly what the
        link carries, and what is known but left out of it."""
        parts = [place, self._dates_text(), self._adults_text()]
        children = self._children_text()
        if children:
            parts.append(children)
        rooms = self._rooms_text()
        if rooms:
            parts.append(rooms)
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
    month, month_year = rec["start_month"], rec["start_year"]
    if month_year is not None and (month_year, month) < (today.year, today.month):
        month, month_year = None, None  # a month that has gone by is no longer a plan
    return ResolvedTrip(
        start_date=start,
        check_in=check_in,
        check_out=check_out,
        nights=nights,
        start_assumed_month=rec["start_assumed_month"] and check_in is not None,
        stay_length=rec["stay_length"],
        stay_unit=rec["stay_unit"],
        adults=rec["adults"],
        children=rec["children"],
        child_ages=ages,
        rooms=rec["rooms"],
        start_date_past=start_past,
        start_month=month,
        start_month_year=month_year,
    )


# --- what the reply is told --------------------------------------------------


@dataclass(frozen=True)
class TripTurn:
    """The trip state for one turn: the resolved trip, plus what this turn's
    message raised (a date that couldn't be used, a child without an age)."""

    trip: ResolvedTrip
    issues: tuple[Issue, ...] = ()
    ask_child_ages: bool = False
    # The rooms asked for don't fit the adults (and this message is about them).
    ask_rooms: bool = False
    today: date | None = None
    # This message changed a detail the search is built from (an offer lapsing
    # doesn't count).
    details_changed: bool = False
    # Someone of a kind that is not clear joined with no age (a cousin, a sister).
    pending_relative: bool = False
    # The traveler settled that person without an age: "adult" or "not_coming".
    pending_resolved: str | None = None
    # This message changed the search itself: it became ready, stopped being
    # ready, or is ready with something else in it. Whatever search button the
    # traveler last saw is out of date. Details that leave the search unready
    # (a start date with no occupancy yet) change nothing here: there was no
    # search before and there is none now.
    search_changed: bool = False
    # How many people the signed-in traveler's profile says they usually travel
    # with: a suggestion to ask about, never a value to use.
    profile_party: int | None = None
    # Remembers that the question about that number was asked (the traveler's
    # "sim" is read against it on the next turn). Set by the orchestrator, which
    # owns the state.
    offer_party: Callable[[int], None] | None = field(default=None, compare=False, repr=False)

    @property
    def must_ask(self) -> bool:
        """Something has to be asked before the search can be right - the
        reply is then that one question, and nothing else."""
        return bool(self.issues) or self.ask_child_ages or self.ask_rooms

    @property
    def party_offer(self) -> int | None:
        """The profile's party size, when who is going is the next thing to ask."""
        asking_who_is_going = self.trip.missing_for_search[:1] == ("adults",)
        if self.profile_party and asking_who_is_going and not self.issues:
            return self.profile_party
        return None

    @property
    def is_informative(self) -> bool:
        return self.trip.is_informative or self.must_ask


def _english_date(d: date) -> str:
    return f"{d:%A} {d.day} {d:%B} {d.year}"


def _month_name(month: int) -> str:
    return date(2000, month, 1).strftime("%B")


def _month_text(trip: "ResolvedTrip") -> str:
    """The month the traveler named, with its year only if they said one."""
    name = _month_name(trip.start_month)
    return f"{name} {trip.start_month_year}" if trip.start_month_year else name


def _issue_line(issue: Issue, today: date | None) -> str:
    if issue.code == "start_in_past" and issue.when is not None:
        return (
            f"The traveler gave a start date that falls on {_english_date(issue.when)}, which "
            f"has already passed (today is {_english_date(today) if today else 'later'}). "
            "Nothing was changed. Ask which date they mean."
        )
    if issue.code == "end_not_after_start":
        return "The traveler gave an end date that is not after the start. Ask them to confirm."
    if issue.code == "month_in_past" and issue.when is not None:
        return (
            f"The traveler named {issue.when:%B %Y}, which has already passed. Nothing was "
            "changed. Ask which month they mean."
        )
    if issue.code == "relative_without_length":
        return (
            "The traveler asked to add or remove nights, but no length of stay is on record, "
            "so there is nothing to add to. Nothing was changed. Ask how many nights in total "
            "they want."
        )
    if issue.code == "relative_without_start":
        return (
            "The traveler asked to add or remove a night at the start, but no start date is on "
            "record to move. Nothing was changed. Ask for the start date."
        )
    if issue.code == "ambiguous_shift":
        return (
            "The traveler said their dates move earlier or later, without saying whether the "
            "whole stay moves (the same number of nights) or only one end changes (and the "
            "number of nights with it). Nothing was changed. Ask which they mean, or for the "
            "new dates."
        )
    if issue.code == "invalid_stay_change":
        return (
            f"That change would leave a stay of {issue.n} nights, which isn't possible. "
            "Nothing was changed. Ask what total length they want."
        )
    if issue.code == "ambiguous_age_correction":
        return (
            "The traveler corrected a child's age, but it is not clear which child (or no child "
            "has that age). Nothing was changed. Ask which child they mean."
        )
    if issue.code == "party_conflict":
        return (
            f"The traveler said some of the {issue.n} people are children, but that leaves no "
            "adult. Nothing was changed. Ask who is going."
        )
    if issue.code == "addition_without_party":
        return (
            "The traveler said someone is joining, but nobody has said yet how many adults are "
            "going, so there is nothing to add them to. Nothing was changed. Ask how many adults "
            "are going in total (and whether any children come, with their ages)."
        )
    if issue.code == "addition_unclear":
        return (
            "The traveler seems to say someone is joining, but not clearly enough to tell whether "
            "they come on top of the people already counted. Nothing was changed. Ask how many "
            "adults and how many children (with their ages) are going in total now."
        )
    if issue.code == "age_or_new_child":
        return (
            "The traveler gave a child's age that differs from the age of the child already "
            "counted, without saying whether it is that same child with a new age or another "
            "child joining. Nothing was changed. Ask which they mean: the same child with the "
            "new age, or one more child."
        )
    if issue.code == "pending_person_unclear":
        return (
            "The traveler said something about the person who just joined, but not clearly "
            "enough to tell whether they are one more adult, a child, or not coming after all. "
            "Nothing was changed. Ask in one short question how old that person is, or whether "
            "they are still coming, calling them what the traveler called them and never "
            '"your child".'
        )
    if issue.code == "party_too_large":
        return (
            "Adding them would make the party larger than a search can carry. Nothing was "
            "changed. Ask how many people are really going."
        )
    return "The traveler gave a date that doesn't exist on the calendar. Ask them to restate it."


_NEEDS = {
    "check_in": "a start date",
    "stay_length": "a length of stay",
    "adults": "the number of adults",
    "child_ages": "every child's age",
    "rooms": "a number of rooms that fits the adults",
}


def _missing_line(turn: TripTurn) -> str:
    """The one question the reply asks next, for the first thing the search is
    missing."""
    trip = turn.trip
    first = trip.missing_for_search[0]
    if first == "check_in" and trip.start_month is not None:
        return (
            f"- Needs clarification: the traveler said {_month_text(trip)} but not the day, so "
            f"the start date is incomplete. Ask which day of {_month_name(trip.start_month)} the "
            "trip starts - just that one question."
        )
    if first == "check_in":
        return (
            "- Needs clarification: the trip's start date is missing. Ask on what date the "
            "trip starts - just that one question."
        )
    if first == "stay_length":
        return (
            "- Needs clarification: the length of the stay is missing. Ask how many nights "
            "(or days) they will stay - just that one question."
        )
    if first == "adults":
        offer = turn.party_offer
        if offer:
            return (
                "- Needs clarification: nobody has said how many adults are going, but the "
                f"traveler's profile says they usually travel with {offer} people. Ask in "
                f"one short question whether those {offer} people are all adults (the "
                f"traveler is one of the {offer} - never phrase it as {offer} more people) - "
                "do not assume it and do not say the search will use that number; if they "
                "say no, they will tell you who is going."
            )
        return (
            "- Needs clarification: nobody has said how many adults are going. Ask how many "
            "adults are going and whether any children come (and, if so, how old each is, "
            "since Booking needs the ages) - one short, natural question."
        )
    if first == "child_ages":
        return (
            "- Needs clarification: a child's age is missing - ask for the age (each age, if "
            "several), briefly, because Booking needs it to price the stay."
        )
    return (
        f"- Needs clarification: {trip.rooms} rooms can't go in the search with "
        f"{trip.adults} adult(s). Ask in one short question whether to change the number "
        f"of adults or use fewer rooms (at most {trip.adults})."
    )


def fact_block(
    turn: TripTurn | None,
    *,
    always: bool = False,
    unsupported_filter: bool = False,
    ask_missing: bool = False,
) -> str:
    """The trip facts for a reply prompt. Empty when there's nothing to say
    (unless `always`, for the stays replies, where "nothing is set" is itself
    the fact). The reply may state dates and numbers of travelers only as
    listed here. `unsupported_filter` is for the stays-action reply alone: the
    traveler asked the search for something it can't do. `ask_missing` is for a
    reply that asks for the next thing the search needs (the stays replies and
    the reply to choosing a destination): it is then shown even when nothing
    is known yet."""
    if turn is None:
        return ""
    asking = ask_missing and not turn.trip.search_ready
    if not (always or asking or turn.is_informative):
        return ""
    trip = turn.trip
    lines = [
        "Trip details Wanderes holds for this traveler - the ONLY dates, stay length, "
        "numbers of travelers and rooms you may state. Never calculate, infer or restate any "
        "other, and never say a detail was set, changed or corrected unless it is listed here. "
        "A number the traveler gives as a child's age is an age: never a date, a check-out day "
        "or a number of nights:"
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
    elif trip.start_month is not None:
        stay = (
            f" The stay is {trip.stay_length} {trip.stay_unit} (counted as {trip.nights} nights)."
            if trip.stay_length is not None
            else ""
        )
        lines.append(
            f"- Dates: the traveler named {_month_text(trip)} but no day, so the start date is "
            "incomplete and the search carries no dates yet. Never state a day or a year they "
            f"did not say.{stay}"
        )
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
        known = ", ".join(str(a) for a in trip.child_ages)
        lines.append(
            f"- Children: {trip.children}, but the age is not known yet, so the "
            "child is NOT included in the Booking search until it is. Never count a child as an "
            "adult and never guess an age."
            if trip.children == 1
            else f"- Children: {trip.children}, of whom the ages known so far are {known}. The "
            "other age(s) are not known yet, so the children are NOT included in the Booking "
            "search until all ages are - ask only for the missing one(s). Never count a child as "
            "an adult and never guess an age."
            if trip.child_ages
            else f"- Children: {trip.children}, but not every age is known yet, so the children "
            "are NOT included in the Booking search until all ages are. Never count a child as an "
            "adult and never guess an age."
        )
    if trip.rooms_in_search:
        lines.append(f"- Rooms: {trip.rooms} - included in the search.")
    elif trip.rooms_conflict:
        lines.append(
            f"- Rooms: {trip.rooms} asked for, but only {trip.adults} adult(s) are going: Booking "
            "needs an adult in every room and would silently use fewer, so the rooms are NOT in "
            "the Booking search. Never say the rooms were set."
        )
    elif trip.rooms is not None:
        lines.append(
            f"- Rooms: {trip.rooms} (noted), not in the search until the number of adults is known."
        )
    carried = []
    if trip.has_dates:
        carried.append(f"dates {trip.check_in.isoformat()} to {trip.check_out.isoformat()}")
    if trip.adults is not None:
        carried.append(f"{trip.adults} adults")
        if trip.children_complete:
            carried.append(f"{trip.children} children")
        if trip.rooms_in_search:
            carried.append(f"{trip.rooms} rooms")
    if trip.search_ready:
        lines.append(
            "- The Booking search link carries exactly: " + ", ".join(carried) + ". Nothing else."
        )
    else:
        needs = ", ".join(_NEEDS[item] for item in trip.missing_for_search)
        lines.append(
            f"- There is NO Booking search action yet: it appears once the trip has {needs}. "
            "Never say a search or a link is ready, prepared or being opened."
        )
    for issue in turn.issues:
        lines.append("- Needs clarification: " + _issue_line(issue, turn.today))
    if turn.pending_relative and trip.children_pending:
        lines.append(
            "- The person who just joined may be a grown-up: their age decides what they count "
            "as. Ask how old they are, calling them what the traveler called them (a cousin, a "
            'brother) and never "your child".'
        )
    if turn.pending_resolved == "adult":
        lines.append(
            "- The person who had just joined, whose age was not known, is counted as one more "
            "adult now: the traveler said they are an adult."
        )
    elif turn.pending_resolved == "not_coming":
        lines.append(
            "- The person who had just joined, whose age was not known, is no longer counted: "
            "the traveler said they are not coming. Nobody else in the party changed."
        )
    if asking and not turn.issues:
        lines.append(_missing_line(turn))
    if turn.ask_child_ages and not ask_missing:
        lines.append(
            "- Needs clarification: a child's age is missing - ask for the age (each age, if "
            "several), briefly, because Booking needs it to price the stay."
        )
    if unsupported_filter:
        lines.append(
            "- The traveler asked for a price level, star rating or amenity. Wanderes has no "
            "verified live prices and can't filter the Booking search by price level, star "
            "rating or amenity, so the search is not limited to it - say so in one sentence, "
            "and that they can apply it once the Booking search is open. Never describe the "
            "search as being for it, and don't recommend specific hotels or quote prices."
        )
    if turn.ask_rooms and not ask_missing:
        lines.append(
            f"- Needs clarification: {trip.rooms} rooms can't go in the search with "
            f"{trip.adults} adult(s). Ask in one short question whether to change the number "
            f"of adults or use fewer rooms (at most {trip.adults})."
        )
    return "\n".join(lines) + "\n\n"
