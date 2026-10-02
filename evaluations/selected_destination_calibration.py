"""A small, frozen calibration set for ai.orchestration's
`selected_destination_name` - the intent field that says "the traveler has
chosen this one place to go to" - and the runner that measures it.

It exists because that field is a judgment the model makes inside the
existing combined intent call, so whether it works can only be measured
against the real model. Everything here runs through the production prompt
and schema (`_validate_intent` included), one call per case, no history
beyond what a case carries. It is deliberately not a framework: one list of
cases, one function, one report.

What a case asserts:
- a *choice* (`expect_select=True`) passes only if the validated
  `selected_destination_name` is set;
- a *non-choice* (`expect_select=False`) passes only if it is null - this is
  the precision side, and the thing a recall improvement must not break;
- `expect_type` additionally pins `message_type` (an aspiration must stay
  `future_intent`);
- `expect_select=None` means either answer is fine (re-setting an already
  chosen place is idempotent).
A failed choice is also classified by *where* it was lost - the model's
`message_type`, the field itself, or `_validate_intent` discarding it - so a
miss can be told apart from a classification problem.

The set is frozen: the cases below are the 18 explicit choices and the 15
controls from the first measurement, plus variants of each pattern. A test
pins its contents. Add new cases as a new category rather than editing these,
or the numbers stop being comparable. Prompt examples must not use the
places in this set (a test checks), or the measurement would be measuring
the examples.

Revision 2 (after the first A/B, on two product decisions - the A/B numbers
are for revision 1): a region inside a country that the traveler explicitly
chooses is a valid selection, so 'quero ir pra Toscana' moved from the
controls to the new `region_choice` category (with two more), and the broad
country request 'quero ir pra Itália' took its place among the controls; a
bare place name that picks one of the options just presented is a choice, so
'Bali' after a list that includes Bali now expects a selection, with
`bare_after_options` (including a name that was NOT offered) and
`bare_no_context` (the same bare names with no options in sight) pinning the
boundary.
"""

from dataclasses import dataclass, field

from ai.orchestration import (
    INTENT_EXTRACTION_SYSTEM_PROMPT,
    INTENT_SCHEMA,
    _drop_unoffered_bare_selection,
    _sanitized_history_messages,
    _validate_intent,
)
from ai.provider import AIMessage


@dataclass(frozen=True)
class Case:
    id: str
    category: str
    message: str
    expect_select: bool | None
    expect_type: str | None = None
    # (role, content) turns the model sees before the message.
    history: tuple = ()
    # The place the case is about, for the "examples never reuse these" test.
    place: str | None = None


_BARCELONA_CHAT = (
    ("user", "quero ir pra Barcelona"),
    ("assistant", "Barcelona é uma ótima escolha! Quer saber o que fazer por lá?"),
)
_OPTIONS_CHAT = (
    ("user", "quero um lugar quente pra relaxar"),
    ("assistant", "Boas opções: Bali, Phuket e Cancún. Qual delas te interessa mais?"),
)


def _cases() -> tuple:
    rows = []

    def add(category, message, expect_select, *, type_=None, history=(), place=None):
        rows.append((category, message, expect_select, type_, history, place))

    rec = "recommendation"

    # --- the 18 explicit choices from the first measurement -------------------
    for message, place in (
        ("quero ir pra Oslo", "Oslo"),
        ("quero ir pra Granada", "Granada"),
        ("quero ir pra Valencia", "Valencia"),
        ("quero ir pra Barcelona", "Barcelona"),
        ("quero ir pra Sevilha em maio", "Sevilha"),
        ("vou pra Paris", "Paris"),
        ("vou passar uns dias em Lisboa", "Lisboa"),
        ("I want to go to Valencia", "Valencia"),
        ("I want to go to Oslo in March", "Oslo"),
        ("let's go with Bali", "Bali"),
        ("Quiero ir a Granada", "Granada"),
        ("Je veux aller à Florence", "Florence"),
        ("voglio andare a Firenze", "Firenze"),
        ("vamos pra Praga em abril", "Praga"),
        ("quero ir pra Barcelona dia 10 desse mes", "Barcelona"),
        ("na verdade quero Madrid", "Madrid"),
        ("quero conhecer Kyoto agora em abril", "Kyoto"),
        ("quero viajar pra Cusco", "Cusco"),
    ):
        add("original_choice", message, True, type_=rec, place=place)

    # --- the 15 controls (14 measured, plus the one that never ran) -----------
    for message, place in (
        ("quero ir pra Noruega", "Noruega"),
        ("quero uma cidade na Noruega", "Noruega"),
        ("quero ir pra Tailândia", "Tailândia"),
        ("quero ir pra Escandinávia", "Escandinávia"),
        ("quero uma cidade na Espanha", "Espanha"),
        ("quero uma praia", None),
        ("Qual é melhor, Oslo ou Bergen?", "Oslo"),
        ("já fui pra Oslo e adorei", "Oslo"),
        ("não quero ir pra Paris", "Paris"),
        ("o que você acha de Oslo?", "Oslo"),
        ("um dia quero conhecer Oslo", "Oslo"),
        ("me recomenda cidades na Itália", "Itália"),
        ("quero ir pra Europa em maio", "Europa"),
        ("e Lisboa, é melhor que isso?", "Lisboa"),
        ("Quanto custa um voo pra Oslo?", "Oslo"),
    ):
        add("original_control", message, False, place=place)

    # --- variants of the choice patterns ---------------------------------------
    for message, place in (
        ("quero ir para Viena", "Viena"),
        ("quero ir para Budapeste", "Budapeste"),
        ("quero ir para Cartagena", "Cartagena"),
        ("quero ir para Hanói", "Hanói"),
        ("quero ir para Amsterdã", "Amsterdã"),
    ):
        add("want_to_go", message, True, type_=rec, place=place)

    for message, place in (
        ("vou para Bruges", "Bruges"),
        ("vou para Dubrovnik", "Dubrovnik"),
        ("vou para Marrakech", "Marrakech"),
        ("vou pra Atenas", "Atenas"),
        ("vou pra Nápoles", "Nápoles"),
    ):
        add("go_to", message, True, type_=rec, place=place)

    for message, place in (
        ("vou passar 5 dias em Praga", "Praga"),
        ("vou ficar três dias em Florença", "Florença"),
        ("vou passar uma semana em Porto", "Porto"),
        ("vou passar o fim de semana em Bruges", "Bruges"),
    ):
        add("stay_days", message, True, type_=rec, place=place)

    for message, place in (
        ("estou planejando viajar para Cusco", "Cusco"),
        ("estou planejando uma viagem para Porto", "Porto"),
        ("I'm planning a trip to Vienna", "Vienna"),
        ("estoy planeando viajar a Granada", "Granada"),
        ("sto pianificando un viaggio a Praga", "Praga"),
    ):
        add("planning", message, True, type_=rec, place=place)

    for message, place in (
        ("estou pensando em ir para Praga", "Praga"),
        ("estou pensando em ir pra Granada", "Granada"),
        ("I'm thinking of going to Valencia", "Valencia"),
        ("estou pensando em passar uns dias em Cusco", "Cusco"),
        ("je pense aller à Lisbonne", "Lisbonne"),
    ):
        add("thinking_of_going", message, True, type_=rec, place=place)

    for message, place in (
        ("quero ir pra Oslo em março", "Oslo"),
        ("vou pra Valencia dia 10", "Valencia"),
        ("quero ir para Praga dia 15 desse mês", "Praga"),
        ("I want to visit Granada in April", "Granada"),
        ("vou para Cusco em julho", "Cusco"),
    ):
        add("with_date", message, True, type_=rec, place=place)

    for message, place in (
        ("I want to go to Oslo", "Oslo"),
        ("We're going to Vienna in June", "Vienna"),
        ("Je vais à Lisbonne", "Lisbonne"),
        ("Quiero ir a Cusco", "Cusco"),
        ("Vado a Firenze la prossima settimana", "Firenze"),
    ):
        add("other_languages", message, True, type_=rec, place=place)

    # --- variants of the non-choices -------------------------------------------
    for message, place in (
        ("um dia quero conhecer Kyoto", "Kyoto"),
        ("algum dia quero ir pra Cusco", "Cusco"),
        ("my dream is to visit Oslo one day", "Oslo"),
        ("sonho em conhecer Praga um dia", "Praga"),
        ("ano que vem quero ir pra Granada", "Granada"),
    ):
        add("future_aspiration", message, False, type_="future_intent", place=place)

    for message, place in (
        ("Praga é melhor que Viena?", "Praga"),
        ("Granada fica longe de Sevilha?", "Granada"),
        ("Vale a pena visitar Cusco?", "Cusco"),
        ("What's the weather like in Oslo in March?", "Oslo"),
        ("Quanto tempo de voo até Lisboa?", "Lisboa"),
    ):
        add("comparison_question", message, False, place=place)

    for message, place in (
        ("minha mãe foi para o Peru", "Peru"),
        ("um amigo meu mora em Oslo", "Oslo"),
        ("já fui pra Granada e adorei", "Granada"),
        ("li sobre Praga num livro", "Praga"),
        ("quero uma praia, não muito longe de Lisboa", "Lisboa"),
    ):
        add("incidental", message, False, place=place)

    for message, place in (
        ("quero ir para a Grécia", "Grécia"),
        ("quero uma cidade em Portugal", "Portugal"),
        ("quero visitar o Peru", "Peru"),
        ("quero ir para a Itália em maio", "Itália"),
        ("quero ir pra Itália", "Itália"),
    ):
        add("region_discovery", message, False, type_=rec, place=place)

    for message, place in (
        ("quero ir pra Toscana", "Toscana"),
        ("vou para a Provença", "Provença"),
        ("quero ir pra Patagônia", "Patagônia"),
    ):
        add("region_choice", message, True, type_=rec, place=place)

    # --- with a conversation behind the message --------------------------------
    add(
        "with_history",
        "e Lisboa, é melhor que isso?",
        False,
        history=_BARCELONA_CHAT,
        place="Lisboa",
    )
    add(
        "with_history",
        "minha mãe foi pra Lisboa e adorou",
        False,
        history=_BARCELONA_CHAT,
        place="Lisboa",
    )
    add(
        "with_history",
        "o que fazer em Barcelona?",
        None,
        history=_BARCELONA_CHAT,
        place="Barcelona",
    )
    add(
        "with_history",
        "na verdade quero Lisboa",
        True,
        type_=rec,
        history=_BARCELONA_CHAT,
        place="Lisboa",
    )
    add("with_history", "Bali", True, type_=rec, history=_OPTIONS_CHAT, place="Bali")
    add("with_history", "quero ir pra Bali", True, type_=rec, history=_OPTIONS_CHAT, place="Bali")

    # --- a bare place name: a choice only when it picks one of the presented options
    add("bare_after_options", "Phuket", True, type_=rec, history=_OPTIONS_CHAT, place="Phuket")
    add("bare_after_options", "Cancún", True, type_=rec, history=_OPTIONS_CHAT, place="Cancún")
    add("bare_after_options", "Lisboa", False, history=_OPTIONS_CHAT, place="Lisboa")
    add("bare_no_context", "Bali", False, place="Bali")
    add("bare_no_context", "Lisboa", False, place="Lisboa")
    add("bare_no_context", "Cusco", False, place="Cusco")

    counts = {}
    cases = []
    for category, message, expect_select, type_, history, place in rows:
        counts[category] = counts.get(category, 0) + 1
        cases.append(
            Case(
                id=f"{category}-{counts[category]:02d}",
                category=category,
                message=message,
                expect_select=expect_select,
                expect_type=type_,
                history=history,
                place=place,
            )
        )
    return tuple(cases)


CASES = _cases()

# What the loss of a choice looks like, from where it happened.
LOST_NOT_RECOMMENDATION = "message_type was not recommendation"
LOST_BY_VALIDATION = "model set a name but validation discarded it"
LOST_BY_MODEL = "model left the field null"


@dataclass
class CaseResult:
    case: Case
    raw_type: str | None
    raw_name: str | None
    final_name: str | None
    passed: bool
    reason: str = ""


@dataclass
class CalibrationReport:
    results: list = field(default_factory=list)

    def by_category(self) -> dict:
        out = {}
        for r in self.results:
            row = out.setdefault(r.case.category, [0, 0])
            row[1] += 1
            row[0] += r.passed
        return out

    def _rate(self, wanted: bool):
        scored = [r for r in self.results if r.case.expect_select is wanted]
        return sum(r.passed for r in scored), len(scored)

    @property
    def choices(self):
        return self._rate(True)

    @property
    def non_choices(self):
        return self._rate(False)


def _judge(case: Case, raw: dict, final: dict) -> tuple:
    final_name = final["selected_destination_name"]
    passed, reason = True, ""
    if case.expect_select is True and final_name is None:
        passed = False
        if raw.get("message_type") != "recommendation":
            reason = LOST_NOT_RECOMMENDATION
        elif raw.get("selected_destination_name"):
            reason = LOST_BY_VALIDATION
        else:
            reason = LOST_BY_MODEL
    elif case.expect_select is False and final_name is not None:
        passed, reason = False, f"selected {final_name!r}"
    if passed and case.expect_type and raw.get("message_type") != case.expect_type:
        passed, reason = False, f"message_type was {raw.get('message_type')!r}"
    return passed, reason


def run_calibration(provider, *, cases=CASES) -> CalibrationReport:
    """One structured call per case, exactly as _extract_intent makes it, but
    keeping the raw answer next to the validated one. Provider errors
    propagate - a half-measured set is worse than none."""
    report = CalibrationReport()
    for case in cases:
        history = [{"role": role, "content": content} for role, content in case.history]
        messages = [
            AIMessage(role="system", content=INTENT_EXTRACTION_SYSTEM_PROMPT),
            *_sanitized_history_messages(history),
            AIMessage(role="user", content=case.message),
        ]
        raw = provider.generate_structured_reply(messages, json_schema=INTENT_SCHEMA, temperature=0)
        final = _validate_intent(dict(raw))
        _drop_unoffered_bare_selection(case.message, final, history)
        passed, reason = _judge(case, raw, final)
        report.results.append(
            CaseResult(
                case=case,
                raw_type=raw.get("message_type"),
                raw_name=raw.get("selected_destination_name"),
                final_name=final["selected_destination_name"],
                passed=passed,
                reason=reason,
            )
        )
    return report


def format_report(report: CalibrationReport) -> str:
    lines = ["== selected_destination_name calibration"]
    for category, (ok, total) in report.by_category().items():
        lines.append(f"  {category:22} {ok:>2}/{total}")
    got, total = report.choices
    lines.append(f"  explicit-choice recall      {got}/{total}")
    got, total = report.non_choices
    lines.append(f"  non-choice precision        {got}/{total}")
    misses = [r for r in report.results if not r.passed]
    if misses:
        lines.append("  misses:")
        for r in misses:
            lines.append(
                f"    {r.case.id:24} {r.case.message!r}  type={r.raw_type} "
                f"raw={r.raw_name!r} final={r.final_name!r}  [{r.reason}]"
            )
    return "\n".join(lines)


# The full-pipeline check that goes with the extraction measurement: where a
# message actually ends up (detail reply, free-form reply, discovery, or
# something else) and what the state remembers. Each conversation runs in its
# own fresh anonymous session; a one-message conversation is a first-turn probe.
PROBE_CONVERSATIONS = (
    # First turns: where each kind of message goes.
    ("barcelona", ("quero ir pra Barcelona",)),
    ("seville", ("quero ir pra Sevilha em maio",)),
    ("lisbon", ("vou passar uns dias em Lisboa",)),
    ("oslo", ("quero ir para Oslo",)),
    ("granada", ("estou pensando em ir para Granada",)),
    ("valencia", ("quero ir pra Valência",)),
    ("prague", ("estou pensando em ir para Praga",)),
    ("cusco", ("quero viajar para Cusco",)),
    ("tuscany", ("quero ir pra Toscana",)),
    # Must stay what they were.
    ("thailand", ("quero ir pra Tailândia",)),
    ("spain-city", ("quero uma cidade na Espanha",)),
    ("italy", ("quero ir pra Itália",)),
    ("kyoto-aspiration", ("um dia quero conhecer Kyoto",)),
    ("bare-name-no-context", ("Bali",)),
    # The choice has to stick, change when the traveler says so, and survive a mention.
    (
        "continuity",
        (
            "quero ir pra Barcelona",
            "conte-me mais",
            "quero algo mais barato",
            "e hospedagem? somos 4",
            "o que fazer lá?",
        ),
    ),
    ("replacement", ("quero ir pra Barcelona", "na verdade quero Madrid", "conte-me mais")),
    (
        "incidental-mention",
        (
            "quero ir pra Barcelona",
            "e Lisboa, é melhor que isso?",
            "minha mãe foi pra Lisboa e adorou",
            "conte-me mais",
        ),
    ),
    ("reopen", ("quero ir pra Barcelona", "quero ver outras opções de cidade na Espanha")),
    ("outside-the-catalog", ("quero ir pra Valência", "conte-me mais")),
    # A bare name picks an option only when options were just presented.
    ("bare-name-after-recommendations", ("quero uma praia na Indonésia", "Bali")),
    ("bare-name-not-offered", ("quero uma praia na Indonésia", "Lisboa")),
)


@dataclass
class ProbeResult:
    conversation: str
    turn: int
    message: str
    route: str
    selected: str | None
    cards: list
    calls: list


class _CountingProvider:
    def __init__(self, inner):
        self.inner = inner
        self.calls = []

    def generate_structured_reply(self, messages, **kwargs):
        self.calls.append(kwargs["json_schema"]["name"])
        return self.inner.generate_structured_reply(messages, **kwargs)

    def generate_reply(self, messages, **kwargs):
        self.calls.append("reply")
        return self.inner.generate_reply(messages, **kwargs)

    def stream_reply(self, messages, **kwargs):
        self.calls.append("stream")
        yield from self.inner.stream_reply(messages, **kwargs)


def run_probes(provider, *, conversations=PROBE_CONVERSATIONS, climate_provider=None) -> list:
    """Run each conversation, turn by turn, through the real orchestration as
    an anonymous visitor (Redis-backed state, like a first-time chat)."""
    import uuid

    from ai import memory
    from ai.orchestration import stream_travel_recommendation

    results = []
    for name, messages in conversations:
        session_key = f"calibration-probe-{uuid.uuid4().hex[:8]}"
        key = memory.conversation_key(user=None, session_key=session_key)
        memory.clear_history(key)
        for turn, message in enumerate(messages, start=1):
            counting = _CountingProvider(provider)
            state_sink: dict = {}
            result = stream_travel_recommendation(
                message,
                user=None,
                session_key=session_key,
                ai_provider=counting,
                climate_provider=climate_provider,
                state_sink=state_sink,
            )
            "".join(result.reply_chunks)
            if result.is_destination_detail:
                route = "detail"
            elif result.accommodation_freeform_name:
                route = "free-form"
            elif result.recommendations:
                route = "discovery"
            else:
                route = "other"
            selected = (state_sink.get("selected_destination") or {}).get("name")
            cards = [r.destination.name for r in result.recommendations]
            results.append(ProbeResult(name, turn, message, route, selected, cards, counting.calls))
        memory.clear_history(key)
    return results


_CALL_LABELS = {
    "travel_message": "intent",
    "climate_budget_signal": "climate",
    "traveler_state_clear_signal": "clear",
    "destination_resolution": "dest-res",
    "freeform_place_resolution": "freeform",
    "stream": "stream",
    "reply": "reply",
}


def format_probes(results) -> str:
    lines = ["== full-pipeline probes"]
    current = None
    for r in results:
        if r.conversation != current:
            current = r.conversation
            lines.append(f"  [{current}]")
        calls = " ".join(_CALL_LABELS.get(c, c) for c in r.calls)
        cards = f" cards={r.cards[:4]}" if r.route == "discovery" else ""
        lines.append(
            f"    {r.turn}. {r.message!r:44} -> {r.route:9} selected={r.selected!r:12} "
            f"calls={len(r.calls)} ({calls}){cards}"
        )
    return "\n".join(lines)
