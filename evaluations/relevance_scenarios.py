"""Focused multi-turn scenarios for conversational relevance: does the reply
answer what the traveler just said, without a tour of the destination they
already chose?

Every scenario starts the way the product does - the traveler chooses Barcelona
(the one turn that should still get the rich reply and its card) - and then
says something that is NOT a request to hear about Barcelona again: a
challenge to an earlier reply, a repeated complaint, a cost question, thanks,
practical questions. A few steps do ask for the destination (what to do, tell
me more, a plan) and should get a real answer. It is not an evaluation
framework: ten scenarios, a handful of deterministic text checks, one report.

The checks are coarse on purpose - they look at the reply's text for the
content the investigation found being pushed onto every follow-up
(attractions, climate, a video offer, a closing question), for invented price
figures and for claims that an operational detail was fixed. They say whether
the behavior moved, not whether a sentence is well written.
"""

import re
from dataclasses import dataclass, field

from evaluations.selected_destination_calibration import _CountingProvider

# What gets recited when the destination is treated as the topic.
_LANDMARKS = re.compile(
    r"sagrada|g[uü]ell|rambla|gaud[ií]|boqueria|barceloneta|g[oó]tico|montju[iï]c|"
    r"batll[oó]|mil[aà]|pedrera|picasso|tibidabo|camp nou",
    re.IGNORECASE,
)
_CLIMATE = re.compile(
    r"°\s?c|\bclima\b|temperatur|\bgraus\b|\bcalor\b|weather|climate", re.IGNORECASE
)
_VIDEO = re.compile(r"v[ií]deo", re.IGNORECASE)
_PRICE = re.compile(
    r"(€|\$|r\$|us\$)\s?\d|\d[\d.,]*\s?(€|euros?|reais|usd|d[oó]lares|dollars)", re.IGNORECASE
)
# A claim that an operational detail was corrected ("ajustei as datas",
# "I updated the link", "a data foi corrigida"), as opposed to understanding
# what the traveler said or saying it can't be changed: only the past or
# passive forms count, so "não posso corrigir as datas" is not a claim.
_DID = (
    r"\b(?:corrigi|ajustei|atualizei|alterei|mudei|corrigimos|ajustamos|atualizamos|alteramos"
    r"|(?:i|we)(?:'ve| have)? (?:corrected|fixed|updated|adjusted|changed))\b"
)
_WAS_DONE = (
    r"\b(?:foi|foram|j[aá] est[aá]o?|was|were|has been|have been) "
    r"(?:corrigid|atualizad|ajustad|alterad|corrected|fixed|updated|adjusted|changed)"
)
_DETAIL = r"(?:datas?|pessoas|viajantes|link|busca|reserva|dates?|travelers|search|booking)"
_FIX_CLAIM = re.compile(
    rf"{_DID}[^.!?\n]{{0,60}}{_DETAIL}|{_DETAIL}[^.!?\n]{{0,40}}{_WAS_DONE}", re.IGNORECASE
)
# Saying plainly that it can't be set or changed from here.
_LIMITS = re.compile(
    r"n[aã]o consigo|n[aã]o posso|n[aã]o tenho como|ainda n[aã]o|n[aã]o [eé] poss[ií]vel|"
    r"n[aã]o controlo|can't|cannot|unable to|not able to|don't have a way",
    re.IGNORECASE,
)

CHECKS = ("attractions", "climate", "video", "price_figures", "fix_claim", "closing_question")


def measure(reply: str) -> dict:
    """The text facts every check is made of."""
    return {
        "chars": len(reply),
        "attractions": len(_LANDMARKS.findall(reply)),
        "climate": len(_CLIMATE.findall(reply)),
        "video": len(_VIDEO.findall(reply)),
        "price_figures": len(_PRICE.findall(reply)),
        "fix_claim": bool(_FIX_CLAIM.search(reply)),
        "closing_question": reply.rstrip().endswith("?"),
        "limits": bool(_LIMITS.search(reply)),
    }


@dataclass(frozen=True)
class Step:
    message: str
    # Whether a destination card (and its stays action) goes with the reply;
    # None = don't care.
    expect_card: bool | None = None
    # Content that must NOT appear (names from CHECKS).
    forbid: tuple = ()
    # Must appear: "rich" (a real destination answer) or "limits" (says plainly
    # it can't set or correct a date or number of travelers).
    require: tuple = ()
    max_chars: int | None = None


_CHOOSE = Step("quero ir pra Barcelona", expect_card=True, require=("rich",))
_NOT_ABOUT_THE_PLACE = ("attractions", "climate", "video", "fix_claim")


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    steps: tuple = field(default_factory=tuple)


SCENARIOS = (
    Scenario(
        "challenge",
        "a challenge about the assistant's own previous output",
        (
            _CHOOSE,
            Step(
                "por que vc presumiu 4 pessoas e me deu dia 10 ao inves de dia 5 ?",
                expect_card=False,
                forbid=(*_NOT_ABOUT_THE_PLACE, "price_figures"),
                max_chars=1000,
            ),
        ),
    ),
    Scenario(
        "repeated-complaint",
        "the same complaint, twice",
        (
            _CHOOSE,
            Step("quero ir dia 05 ficar 3 dias", forbid=("video", "fix_claim")),
            Step(
                "continua com a data errada",
                expect_card=False,
                forbid=_NOT_ABOUT_THE_PLACE,
                max_chars=1000,
            ),
            Step(
                "ainda está errado",
                expect_card=False,
                forbid=_NOT_ABOUT_THE_PLACE,
                max_chars=1000,
            ),
        ),
    ),
    Scenario(
        "cost",
        "quanto custa?",
        (
            _CHOOSE,
            Step(
                "quanto custa?",
                expect_card=False,
                forbid=("attractions", "climate", "video", "price_figures"),
                max_chars=1100,
            ),
        ),
    ),
    Scenario(
        "activities",
        "o que fazer em Barcelona?",
        (_CHOOSE, Step("o que fazer em Barcelona?", expect_card=False, require=("rich",))),
    ),
    Scenario(
        "tell-me-more",
        "conte-me mais sobre Barcelona",
        (_CHOOSE, Step("conte-me mais sobre Barcelona", require=("rich",))),
    ),
    Scenario(
        "stays",
        "e hospedagem?",
        (
            _CHOOSE,
            Step(
                "e hospedagem? somos 2",
                expect_card=True,
                forbid=("fix_claim", "price_figures", "video", "climate"),
            ),
        ),
    ),
    Scenario(
        "date-correction",
        "a date correction",
        (
            _CHOOSE,
            Step("quero ir dia 05 ficar 3 dias", forbid=("video", "fix_claim")),
            Step(
                "na verdade é dia 06",
                forbid=_NOT_ABOUT_THE_PLACE,
                max_chars=900,
            ),
        ),
    ),
    Scenario(
        "thanks",
        "obrigado",
        (
            _CHOOSE,
            Step(
                "obrigado",
                expect_card=False,
                forbid=(*_NOT_ABOUT_THE_PLACE, "closing_question"),
                max_chars=350,
            ),
        ),
    ),
    Scenario(
        "ordinary-follow-ups",
        "three consecutive ordinary follow-ups",
        (
            _CHOOSE,
            Step(
                "qual a moeda de lá?", expect_card=False, forbid=_NOT_ABOUT_THE_PLACE, max_chars=900
            ),
            Step(
                "preciso de adaptador de tomada?",
                expect_card=False,
                forbid=_NOT_ABOUT_THE_PLACE,
                max_chars=900,
            ),
            Step(
                "fala-se inglês lá?", expect_card=False, forbid=_NOT_ABOUT_THE_PLACE, max_chars=900
            ),
        ),
    ),
    Scenario(
        "broad-exploratory",
        "a broad exploratory request",
        (
            _CHOOSE,
            Step("me ajuda a montar um roteiro de 3 dias?", expect_card=False, require=("rich",)),
        ),
    ),
)


@dataclass
class StepResult:
    scenario: str
    index: int
    step: Step
    route: str
    card: bool
    measures: dict
    failures: list
    reply: str


def _route_of(result, prompt: str) -> str:
    if result.is_destination_detail:
        return "detail"
    if result.accommodation_freeform_name:
        return "free-form"
    if result.recommendations:
        return "discovery"
    if "is already the traveler's chosen destination" in prompt:
        return "carried"
    if "follow-up question about" in prompt:
        return "activity"
    return "other"


def check_step(step: Step, *, card: bool, measures: dict) -> list:
    """The failed expectations of one step, as readable strings."""
    failures = []
    if step.expect_card is not None and card != step.expect_card:
        failures.append(f"card {'present' if card else 'absent'}, expected the opposite")
    for name in step.forbid:
        if measures[name]:
            failures.append(f"forbidden {name} ({measures[name]})")
    if "limits" in step.require and not measures["limits"]:
        failures.append("does not say plainly that it can't set or correct that")
    if "rich" in step.require and not (measures["attractions"] >= 2 or measures["chars"] >= 700):
        failures.append("not a real destination answer")
    if step.max_chars is not None and measures["chars"] > step.max_chars:
        failures.append(f"too long ({measures['chars']} > {step.max_chars} chars)")
    return failures


def run_relevance(provider, *, scenarios=SCENARIOS, climate_provider=None) -> list:
    """Run each scenario as a fresh anonymous conversation through the real
    orchestration, turn by turn, and check every step."""
    import uuid

    from ai import memory
    from ai.orchestration import stream_travel_recommendation

    results = []
    for scenario in scenarios:
        session_key = f"relevance-{uuid.uuid4().hex[:8]}"
        key = memory.conversation_key(user=None, session_key=session_key)
        memory.clear_history(key)
        for index, step in enumerate(scenario.steps, start=1):
            counting = _CountingProvider(provider)
            result = stream_travel_recommendation(
                step.message,
                user=None,
                session_key=session_key,
                ai_provider=counting,
                climate_provider=climate_provider,
            )
            reply = "".join(result.reply_chunks)
            card = bool(result.recommendations or result.accommodation_freeform_name)
            measures = measure(reply)
            results.append(
                StepResult(
                    scenario=scenario.id,
                    index=index,
                    step=step,
                    route=_route_of(result, counting.stream_prompt),
                    card=card,
                    measures=measures,
                    failures=check_step(step, card=card, measures=measures),
                    reply=reply,
                )
            )
        memory.clear_history(key)
    return results


def format_report(results: list, *, show_replies: bool = False) -> str:
    lines = ["== conversational relevance"]
    current = None
    for r in results:
        if r.scenario != current:
            current = r.scenario
            title = next(s.title for s in SCENARIOS if s.id == current)
            lines.append(f"  [{current}] {title}")
        m = r.measures
        status = "ok  " if not r.failures else "FAIL"
        card = "Y" if r.card else "n"
        question = "Y" if m["closing_question"] else "n"
        lines.append(
            f"    {status} {r.index}. {r.step.message!r:58} route={r.route:9} card={card} "
            f"chars={m['chars']:<5} landmarks={m['attractions']} climate={m['climate']} "
            f"video={m['video']} q={question}"
        )
        for failure in r.failures:
            lines.append(f"           - {failure}")
        if show_replies:
            lines.append("           > " + r.reply[:240].replace("\n", " "))
    later = [r for r in results if r.index > 1]
    off_topic = [r for r in later if "attractions" in r.step.forbid]
    fresh = [r for r in results if r.index == 1]
    passed = sum(not r.failures for r in results)

    def count(rows, name):
        return sum(bool(r.measures[name]) for r in rows)

    lines.append(f"  steps passing: {passed}/{len(results)}")
    lines.append(
        f"  fresh choice kept rich with its card: {sum(not r.failures for r in fresh)}/{len(fresh)}"
    )
    n = len(later)
    lines.append(
        f"  later turns with landmarks: {count(later, 'attractions')}/{n}"
        f" | with a video offer: {count(later, 'video')}/{n}"
        f" | with climate: {count(later, 'climate')}/{n}"
        f" | ending in a question: {count(later, 'closing_question')}/{n}"
    )
    lines.append(
        "  turns that should not be about the place but carry landmarks: "
        f"{count(off_topic, 'attractions')}/{len(off_topic)}"
    )
    return "\n".join(lines)
