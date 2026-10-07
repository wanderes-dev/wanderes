"""A small frozen set of phrases for the trip-details extraction: does the
model report the components the traveler stated - and nothing else?

Thirty phrases, no more, and no tuning loop around them: it exists to show
the extraction behaves on the shapes this feature depends on (a bare day, a
length, a range, who is going, an age given as a reply, a detail withdrawn)
and on the ones that must yield nothing (a complaint about an earlier reply,
a past trip, someone else's trip). It runs the real `_extract_trip_details_signal`
- the same call, prompt and schema as production - and compares only the
components, never a calculated date (the model is never asked for one).
"""

from dataclasses import dataclass, field

# A leaf the phrase doesn't pin down.
ANY = "<any>"

_BLANK_START = {"day": None, "month": None, "year": None, "relative_month": None}
_BLANK_END = {"day": None, "month": None}


@dataclass(frozen=True)
class Phrase:
    id: str
    message: str
    # Only the components the phrase states; everything else must be null/empty.
    expect: dict = field(default_factory=dict)
    # The assistant's last message, for a reply that needs it to be understood.
    question: str | None = None


def expected_components(expect: dict) -> dict:
    return {
        "start": {**_BLANK_START, **expect.get("start", {})},
        "end": {**_BLANK_END, **expect.get("end", {})},
        "stay_length": expect.get("stay_length"),
        "stay_unit": expect.get("stay_unit"),
        "adults": expect.get("adults"),
        "children": expect.get("children"),
        "child_ages": expect.get("child_ages", []),
        "cleared_fields": expect.get("cleared_fields", []),
    }


def differences(parsed: dict, expect: dict) -> list[str]:
    """What differs between the validated components and what the phrase states."""
    wanted = expected_components(expect)
    found = []
    for key, want in wanted.items():
        got = parsed[key]
        if isinstance(want, dict):
            for leaf, leaf_want in want.items():
                if leaf_want != ANY and got[leaf] != leaf_want:
                    found.append(f"{key}.{leaf}: wanted {leaf_want!r}, got {got[leaf]!r}")
        elif key == "cleared_fields":
            if sorted(got) != sorted(want):
                found.append(f"{key}: wanted {sorted(want)!r}, got {sorted(got)!r}")
        elif want != ANY and got != want:
            found.append(f"{key}: wanted {want!r}, got {got!r}")
    return found


PHRASES = (
    # --- when
    Phrase("bare-day", "quero ir dia 5", {"start": {"day": 5}}),
    Phrase(
        "day-05-and-days",
        "quero ir dia 05 ficar 3 dias",
        {"start": {"day": 5}, "stay_length": 3, "stay_unit": "days"},
    ),
    Phrase(
        "this-month",
        "quero chegar dia 20 deste mês",
        {"start": {"day": 20, "month": ANY, "relative_month": "this"}},
    ),
    Phrase(
        "next-month",
        "vamos dia 5 do mês que vem",
        {"start": {"day": 5, "month": ANY, "relative_month": "next"}},
    ),
    Phrase("named-month", "quero ir em 12 de dezembro", {"start": {"day": 12, "month": 12}}),
    Phrase(
        "with-year",
        "chegamos dia 3 de março de 2027",
        {"start": {"day": 3, "month": 3, "year": 2027}},
    ),
    Phrase("range", "de 5 a 8", {"start": {"day": 5}, "end": {"day": 8}}),
    Phrase(
        "range-with-month",
        "de 5 a 8 de novembro",
        {"start": {"day": 5, "month": 11}, "end": {"day": 8, "month": ANY}},
    ),
    Phrase(
        "regression-this-month-nights",
        "quero ir dia 5 deste mês, ficar 3 noites",
        {
            "start": {"day": 5, "month": ANY, "relative_month": "this"},
            "stay_length": 3,
            "stay_unit": "nights",
        },
    ),
    # --- how long
    Phrase(
        "days-alone", "Quero ir pra Barcelona 10 dias", {"stay_length": 10, "stay_unit": "days"}
    ),
    Phrase("nights", "vou ficar 4 noites", {"stay_length": 4, "stay_unit": "nights"}),
    Phrase("weeks-in-english", "we'll stay two weeks", {"stay_length": 14, "stay_unit": "days"}),
    # --- who
    Phrase("adults-and-a-child", "3 adultos e uma criança", {"adults": 3, "children": 1}),
    Phrase(
        "child-with-age",
        "3 adultos e uma criança de 5 anos",
        {"adults": 3, "children": 1, "child_ages": [5]},
    ),
    Phrase(
        "family-with-a-son",
        "eu, minha esposa e meu filho de 8 anos",
        {"adults": 2, "children": 1, "child_ages": [8]},
    ),
    Phrase("bare-total", "somos 4", {"adults": 4}),
    Phrase("alone", "vou sozinho", {"adults": 1}),
    Phrase(
        "two-and-two",
        "2 adultos e 2 crianças, de 3 e 7 anos",
        {"adults": 2, "children": 2, "child_ages": [3, 7]},
    ),
    # --- an answer that needs the question
    Phrase(
        "age-reply",
        "5 anos",
        {"child_ages": [5]},
        question="Quantos anos tem a criança? A Booking precisa da idade.",
    ),
    Phrase(
        "number-reply",
        "3",
        {"adults": 3},
        question="Quantos adultos vão viajar?",
    ),
    Phrase(
        "two-ages-reply",
        "uma de 4 e outra de 9",
        {"child_ages": [4, 9]},
        question="Quantos anos tem cada criança?",
    ),
    # --- taking something back
    Phrase("forget-the-start", "esquece a data de início", {"cleared_fields": ["start"]}),
    Phrase("forget-the-adults", "esquece o número de adultos", {"cleared_fields": ["adults"]}),
    # --- other languages
    Phrase(
        "english",
        "I'd like to go on the 12th of May for 4 nights, 2 adults",
        {"start": {"day": 12, "month": 5}, "stay_length": 4, "stay_unit": "nights", "adults": 2},
    ),
    Phrase(
        "spanish",
        "salimos el 3 de enero, 2 adultos y 2 niños",
        {"start": {"day": 3, "month": 1}, "adults": 2, "children": 2},
    ),
    Phrase(
        "french",
        "nous partons le 15 juillet pour une semaine",
        {
            "start": {"day": 15, "month": 7},
            "end": {"day": ANY, "month": ANY},  # the resolver ignores an end next to a length
            "stay_length": 7,
            "stay_unit": "days",
        },
    ),
    # --- must yield nothing
    Phrase(
        "complaint-about-an-earlier-reply",
        "por que vc presumiu 4 pessoas e me deu dia 10 ao inves de dia 5 ?",
        {},
    ),
    Phrase("a-past-trip", "estive em Roma em 2019 com 3 amigos e adorei", {}),
    # Known residual, left failing on purpose: a date from someone else's trip
    # comes back as a bare `start.day`, indistinguishable in the components
    # from the traveler's own "dia 12" - the result carries no "whose trip",
    # so nothing downstream can safely tell them apart.
    Phrase("someone-elses-trip", "meu primo vai pra Paris dia 12 com 3 filhos", {}),
    Phrase("not-trip-details", "o que fazer lá?", {}),
)


@dataclass
class PhraseResult:
    phrase: Phrase
    parsed: dict
    differences: list[str]

    @property
    def passed(self) -> bool:
        return not self.differences


def run_trip_details_set(provider, phrases=PHRASES) -> list[PhraseResult]:
    """Run every phrase through the production extraction call."""
    from ai.orchestration import _extract_trip_details_signal

    results = []
    for phrase in phrases:
        history = [{"role": "assistant", "content": phrase.question}] if phrase.question else []
        parsed = _extract_trip_details_signal(phrase.message, ai_provider=provider, history=history)
        results.append(PhraseResult(phrase, parsed, differences(parsed, phrase.expect)))
    return results


def format_report(results: list[PhraseResult]) -> str:
    lines = ["== trip-details extraction (frozen set)"]
    for r in results:
        lines.append(f"  {'ok  ' if r.passed else 'FAIL'} {r.phrase.id:34} {r.phrase.message!r}")
        for d in r.differences:
            lines.append(f"         - {d}")
    passed = sum(r.passed for r in results)
    lines.append(f"  phrases matching: {passed}/{len(results)}")
    return "\n".join(lines)
