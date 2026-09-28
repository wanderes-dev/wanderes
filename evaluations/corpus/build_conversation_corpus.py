"""Builds evaluations/corpus/conversations.jsonl - the Cycle 2 multi-turn
conversation corpus. Separate from, and never modifies, build_corpus.py's
single-request corpus.

Every destination/country/trip_type/cost_of_living fact referenced below
was checked directly against travel/data/curated_destinations.json (via
travel.management.commands.load_destinations's own Portuguese-label ->
English-enum mapping - the raw dataset's trip_type field is still
"Cultura/história"-style text, normalized to the strict beach/city/
nature/culture choice by taking the first segment). expected_state only
ever uses the real RecommendationRequest field names.

Run with: py evaluations/corpus/build_conversation_corpus.py from the
repo root - a plain script, no Django settings needed.
"""

from __future__ import annotations

import json
from pathlib import Path

OUTPUT_PATH = Path(__file__).parent / "conversations.jsonl"

_conversations: list[dict] = []


def t(
    message,
    *,
    language="en",
    expected_state=None,
    expected_transitions=None,
    references_turn_index=None,
    references_ordinal=None,
    expects_clarification=False,
    notes="",
):
    return {
        "message": message,
        "language": language,
        "expected_state": expected_state,
        "expected_transitions": expected_transitions,
        "references_turn_index": references_turn_index,
        "references_ordinal": references_ordinal,
        "expects_clarification": expects_clarification,
        "notes": notes,
    }


def c(
    id,
    split,
    family,
    turns,
    *,
    profile_overrides=None,
    notes="",
    metamorphic_pair=None,
    metamorphic_axis=None,
):
    conversation = {
        "id": id,
        "split": split,
        "family": family,
        "turns": turns,
        "profile_overrides": profile_overrides,
        "notes": notes,
        "metamorphic_pair": metamorphic_pair,
        "metamorphic_axis": metamorphic_axis,
    }
    _conversations.append(conversation)
    return conversation


# ============================================================
# A. DRIFT - preference drift / change of mind. ~7 conversations.
# ============================================================

c(
    "DRIFT-001",
    "dev",
    "drift",
    [
        t(
            "I want somewhere warm with beaches in November.",
            expected_state={"month": 11, "min_temp_c": 28, "trip_type": "beach"},
            expected_transitions={"month": "added", "min_temp_c": "added", "trip_type": "added"},
        ),
        t(
            "Actually, forget the beach. My girlfriend would rather have cities and culture.",
            expected_state={"month": 11, "min_temp_c": 28, "trip_type": None},
            expected_transitions={
                "month": "retained",
                "min_temp_c": "retained",
                "trip_type": "superseded",
            },
            notes="trip_type=beach must not survive - the traveler explicitly retracted it. "
            "warm/November persist since neither was contradicted.",
        ),
        t(
            "We've already been to Rome and Barcelona.",
            expected_state={"excluded_slugs": ["roma-it", "barcelona-es"]},
            expected_transitions={"excluded_slugs": "added"},
        ),
        t(
            "Budget is around 1500 euros each, so nothing too cheap but nothing crazy either.",
            expected_state={"excluded_slugs": ["roma-it", "barcelona-es"]},
            expected_transitions={"excluded_slugs": "retained"},
            notes="The corpus's headline scenario - real currency amounts aren't mapped to "
            "max_cost_of_living by the current schema (no anchor for a literal number), "
            "so this checkpoint only asserts what's actually verifiable: the exclusions "
            "from the prior turn survived a message about an unrelated dimension.",
        ),
    ],
    notes="The exact scenario from the Cycle 2 brief - warm retained, beach superseded, "
    "Rome/Barcelona excluded, budget stated (currency, not schema-mapped - see turn 4's note).",
)

c(
    "DRIFT-002",
    "dev",
    "drift",
    [
        t(
            "quero uma praia bem barata",
            language="pt",
            expected_state={"trip_type": "beach", "max_cost_of_living": 2},
        ),
        t(
            "pensando melhor, acho que prefiro mesmo uma cidade",
            language="pt",
            expected_state={"trip_type": "city"},
            expected_transitions={"trip_type": "superseded"},
            notes="beach -> city is a direct, unambiguous supersession on the same field.",
        ),
    ],
)

c(
    "DRIFT-003",
    "dev",
    "drift",
    [
        t(
            "quero um lugar bem quente para viajar",
            language="pt",
            expected_state={"min_temp_c": 28},
        ),
        t(
            "na verdade, pensando bem, prefiro algo mais ameno, nem tão quente",
            language="pt",
            expected_state={"min_temp_c": None},
            expected_transitions={"min_temp_c": "superseded"},
            notes="'hot' retracted in favor of 'mild' - min_temp_c=28 must not linger.",
        ),
    ],
)

c(
    "DRIFT-004",
    "dev",
    "drift",
    [
        t(
            "quero algo bem barato para viajar",
            language="pt",
            expected_state={"max_cost_of_living": 2},
        ),
        t(
            "na verdade pode ser um pouco mais confortável, não precisa ser o mais barato",
            language="pt",
            expected_state={"max_cost_of_living": None},
            expected_transitions={"max_cost_of_living": "superseded"},
            notes="A style/comfort word ('confortável'), not a recognized budget anchor - per "
            "the real prompt's own rule, this should null out the prior cheap anchor rather "
            "than mapping to a new tier.",
        ),
    ],
)

c(
    "DRIFT-005",
    "dev",
    "drift",
    [
        t(
            "quero conhecer a Europa",
            language="pt",
            expected_state={"continent": "europe"},
        ),
        t(
            "na verdade, pensando melhor, acho que prefiro a Ásia",
            language="pt",
            expected_state={"continent": "asia"},
            expected_transitions={"continent": "superseded"},
        ),
    ],
)

c(
    "DRIFT-006",
    "holdout",
    "drift",
    [
        t(
            "quero uma viagem de cultura pela Itália",
            language="pt",
            expected_state={"trip_type": "culture", "country": "Italy"},
        ),
        t(
            "só não quero ir para Roma, já fui",
            language="pt",
            expected_state={
                "trip_type": "culture",
                "country": "Italy",
                "excluded_slugs": ["roma-it"],
            },
            expected_transitions={
                "trip_type": "retained",
                "country": "retained",
                "excluded_slugs": "added",
            },
        ),
    ],
)

c(
    "DRIFT-007",
    "dev",
    "drift",
    [
        t(
            "I want a cheap beach trip.",
            expected_state={"trip_type": "beach", "max_cost_of_living": 2},
        ),
        t(
            "Actually, let's do a nature trip instead - budget doesn't matter as much now.",
            expected_state={"trip_type": "nature", "max_cost_of_living": None},
            expected_transitions={"trip_type": "superseded", "max_cost_of_living": "superseded"},
            notes="Two fields superseded in the same turn.",
        ),
    ],
)


# ============================================================
# B. CORRECTION - a stated value corrected shortly after. ~7 conversations.
# ============================================================

c(
    "CORR-001",
    "dev",
    "correction",
    [
        t("quero viajar em outubro", language="pt", expected_state={"month": 10}),
        t(
            "desculpa, quis dizer novembro",
            language="pt",
            expected_state={"month": 11},
            expected_transitions={"month": "superseded"},
        ),
    ],
)

c(
    "CORR-002",
    "dev",
    "correction",
    [
        t(
            "quero algo bem barato para viajar",
            language="pt",
            expected_state={"max_cost_of_living": 2},
        ),
        t(
            "desculpa, quis dizer moderado, não o mais barato possível",
            language="pt",
            expected_state={"max_cost_of_living": 4},
            expected_transitions={"max_cost_of_living": "superseded"},
        ),
    ],
)

c(
    "CORR-003",
    "dev",
    "correction",
    [
        t("orçamento de 800 euros no total", language="pt", expected_state={}),
        t(
            "desculpa, quis dizer 800 euros por pessoa",
            language="pt",
            expected_state={"max_cost_of_living": None},
            notes="Deliberately documents a real schema gap, not chased as a bug: the current "
            "extraction has no anchor mapping a literal currency figure to max_cost_of_living "
            "at all (checked directly in CLIMATE_BUDGET_SYSTEM_PROMPT), total or per-person - "
            "both turns are expected to leave it null. See documentation/"
            "18_CONVERSATION_EVALUATION_FRAMEWORK.md for the architecture trace this is based on.",
        ),
    ],
)

c(
    "CORR-004",
    "dev",
    "correction",
    [
        t("quero conhecer a Itália", language="pt", expected_state={"country": "Italy"}),
        t(
            "não, desculpa, quis dizer a Espanha",
            language="pt",
            expected_state={"country": "Spain"},
            expected_transitions={"country": "superseded"},
        ),
    ],
)

c(
    "CORR-005",
    "dev",
    "correction",
    [
        t("quero uma praia", language="pt", expected_state={"trip_type": "beach"}),
        t(
            "não, quis dizer uma cidade mesmo",
            language="pt",
            expected_state={"trip_type": "city"},
            expected_transitions={"trip_type": "superseded"},
        ),
    ],
)

c(
    "CORR-006",
    "holdout",
    "correction",
    [
        t("We're traveling in October.", expected_state={"month": 10}),
        t(
            "Sorry - I meant November.",
            expected_state={"month": 11},
            expected_transitions={"month": "superseded"},
        ),
    ],
)

c(
    "CORR-007",
    "dev",
    "correction",
    [
        t("quero um lugar bem quente", language="pt", expected_state={"min_temp_c": 28}),
        t(
            "na verdade quis dizer ameno, não quente",
            language="pt",
            expected_state={"min_temp_c": 18},
            expected_transitions={"min_temp_c": "superseded"},
        ),
    ],
)


# ============================================================
# C. CONTRADICTION - a later statement resolves (overrides) an earlier,
# incompatible one. ~7 conversations.
# ============================================================

c(
    "CONTRA-001",
    "dev",
    "contradiction",
    [
        t(
            "quero uma viagem para uma cidade agitada",
            language="pt",
            expected_state={"trip_type": "city"},
        ),
        t(
            "pensando bem, vamos com crianças, prefiro algo mais tranquilo, tipo natureza",
            language="pt",
            expected_state={"trip_type": "nature"},
            expected_transitions={"trip_type": "superseded"},
            notes="A real family-context contradiction, not just a style change - the earlier "
            "'agitada'/city preference must not coexist with the later 'tranquilo' one.",
        ),
    ],
)

c(
    "CONTRA-002",
    "dev",
    "contradiction",
    [
        t("quero algo bem barato", language="pt", expected_state={"max_cost_of_living": 2}),
        t(
            "na verdade conforto importa mais que preço agora",
            language="pt",
            expected_state={"max_cost_of_living": None},
            expected_transitions={"max_cost_of_living": "superseded"},
            notes="'comfort matters more than price' is the real prompt's own 'wants luxury' "
            "case - should null out, not blend with, the earlier cheap anchor.",
        ),
    ],
)

c(
    "CONTRA-003",
    "dev",
    "contradiction",
    [
        t("quero conhecer a Ásia", language="pt", expected_state={"continent": "asia"}),
        t(
            "na verdade, pensando bem, quero ficar na Europa mesmo",
            language="pt",
            expected_state={"continent": "europe"},
            expected_transitions={"continent": "superseded"},
        ),
    ],
)

c(
    "CONTRA-004",
    "dev",
    "contradiction",
    [
        t("quero um lugar bem quente", language="pt", expected_state={"min_temp_c": 28}),
        t(
            "na verdade prefiro um lugar bem friozinho",
            language="pt",
            expected_state={"min_temp_c": None, "max_temp_c": 15},
            expected_transitions={"min_temp_c": "superseded", "max_temp_c": "added"},
        ),
    ],
)

c(
    "CONTRA-005",
    "holdout",
    "contradiction",
    [
        t(
            "quero muita vida noturna e agito",
            language="pt",
            expected_state={},
            notes="'nightlife' has no direct schema field - this turn establishes a vibe only, "
            "nothing machine-checked yet.",
        ),
        t(
            "pensando melhor, vamos com crianças, então prefiro algo tranquilo",
            language="pt",
            expects_clarification=False,
            expected_state={"trip_type": None},
            notes="No prior trip_type was ever set, so there's nothing concrete to supersede - "
            "'tranquilo' alone doesn't map cleanly to one of the four categories either "
            "(matches beach/nature/culture equally well), so trip_type staying null is the "
            "correct, non-force-fit outcome, not a failure.",
        ),
    ],
)

c(
    "CONTRA-006",
    "dev",
    "contradiction",
    [
        t("I want somewhere very cheap.", expected_state={"max_cost_of_living": 2}),
        t(
            "Price isn't really important; comfort matters more.",
            expected_state={"max_cost_of_living": None},
            expected_transitions={"max_cost_of_living": "superseded"},
        ),
    ],
)

c(
    "CONTRA-007",
    "dev",
    "contradiction",
    [
        t("quero ir para a Itália", language="pt", expected_state={"country": "Italy"}),
        t(
            "na verdade não, vamos pra Tailândia",
            language="pt",
            expected_state={"country": "Thailand", "continent": "asia"},
            expected_transitions={"country": "superseded", "continent": "superseded"},
        ),
    ],
)


# ============================================================
# D. REFERENCE - resolving "the second option"/"something like the
# first one" against what was actually shown. ~7 conversations. Given
# production has no dedicated reference-resolution mechanism (see the
# architecture trace), these are expected to surface real gaps, not
# assumed to pass.
# ============================================================

c(
    "REF-001",
    "dev",
    "reference",
    [
        t(
            "quero uma praia bem barata em outubro",
            language="pt",
            expected_state={"trip_type": "beach", "month": 10},
        ),
        t(
            "me conta mais sobre a segunda opção",
            language="pt",
            references_turn_index=0,
            references_ordinal=2,
        ),
    ],
)

c(
    "REF-002",
    "dev",
    "reference",
    [
        t(
            "quero conhecer cidades culturais na Europa",
            language="pt",
            expected_state={"trip_type": "culture", "continent": "europe"},
        ),
        t(
            "me fala mais sobre a primeira",
            language="pt",
            references_turn_index=0,
            references_ordinal=1,
        ),
    ],
)

c(
    "REF-003",
    "dev",
    "reference",
    [
        t("quero uma praia de luxo", language="pt", expected_state={"trip_type": "beach"}),
        t(
            "algo parecido com a terceira opção, mas mais barato",
            language="pt",
            references_turn_index=0,
            references_ordinal=3,
        ),
    ],
)

c(
    "REF-004",
    "holdout",
    "reference",
    [
        t("quero uma viagem de natureza", language="pt", expected_state={"trip_type": "nature"}),
        t(
            "não essa — me fala das outras duas",
            language="pt",
            references_turn_index=0,
            references_ordinal=2,
            notes="Ambiguous ordinal on purpose ('the other two') - scored against whichever "
            "single destination the resolver can reasonably anchor to (position 2); a real "
            "product improvement here might resolve a set, not just one ordinal.",
        ),
    ],
)

c(
    "REF-005",
    "dev",
    "reference",
    [
        t(
            "I want a budget beach trip.",
            expected_state={"trip_type": "beach", "max_cost_of_living": 2},
        ),
        t("Tell me more about the second one.", references_turn_index=0, references_ordinal=2),
    ],
)

c(
    "REF-006",
    "dev",
    "reference",
    [
        t(
            "I want to explore cultural cities in Asia.",
            expected_state={"trip_type": "culture", "continent": "asia"},
        ),
        t("I liked the second option.", references_turn_index=0, references_ordinal=2),
        t("What's the best time of year to go?", references_turn_index=0, references_ordinal=2),
    ],
)

c(
    "REF-007",
    "dev",
    "reference",
    [
        t("quero uma praia tranquila", language="pt", expected_state={"trip_type": "beach"}),
        t(
            "a propósito, meu voo tem escala em Lisboa",
            language="pt",
            notes="irrelevant aside between the options and the reference",
        ),
        t(
            "voltando, me conta sobre a segunda opção",
            language="pt",
            references_turn_index=0,
            references_ordinal=2,
        ),
    ],
)


# ============================================================
# E. MEMORY - long-range persistence/exclusion across several turns.
# ~7 conversations. MEM-001 ports MTT-010 verbatim, per the Cycle 2
# brief's explicit instruction, unfixed.
# ============================================================

c(
    "MEM-001",
    "dev",
    "memory",
    [
        t(
            "cidade no japao, outubro, ja fui a toquio e osaka, quero outra",
            language="pt",
            expected_state={
                "month": 10,
                "trip_type": "city",
                "country": "Japan",
                "excluded_slugs": ["toquio-jp", "osaka-jp"],
            },
        ),
        t(
            "e tem algum lugar assim que seja mais barato?",
            language="pt",
            expected_state={
                "month": 10,
                "trip_type": "city",
                "country": "Japan",
                "excluded_slugs": ["toquio-jp", "osaka-jp"],
            },
            expected_transitions={
                "month": "retained",
                "trip_type": "retained",
                "country": "retained",
                "excluded_slugs": "retained",
            },
            notes="A natural second turn added to make this a real conversation (the framework "
            "requires at least two turns) - re-checks the exact same state one exchange later, "
            "since MTT-010's own message is turn 1 verbatim.",
        ),
    ],
    notes="Turn 1 ports evaluations/corpus/scenarios.jsonl's MTT-010 verbatim - the Cycle 1.6 "
    "finding reproduced 5/5 real full-pipeline calls: trip_type and country both come back null "
    "despite the message explicitly stating 'cidade' and 'no japao'. Included exactly as "
    "required, not fixed here.",
)

c(
    "MEM-002",
    "dev",
    "memory",
    [
        t(
            "já fui ao Japão, não quero voltar lá",
            language="pt",
            expected_state={
                "excluded_slugs": ["toquio-jp", "kyoto-jp", "osaka-jp", "hiroshima-jp"]
            },
        ),
        t("e queria algo de praia", language="pt", expected_state={"trip_type": "beach"}),
        t("pode ser barato", language="pt", expected_state={"max_cost_of_living": 2}),
        t(
            "então, onde você recomenda?",
            language="pt",
            expected_state={
                "trip_type": "beach",
                "max_cost_of_living": 2,
                "excluded_slugs": ["toquio-jp", "kyoto-jp", "osaka-jp", "hiroshima-jp"],
            },
            expected_transitions={
                "trip_type": "retained",
                "max_cost_of_living": "retained",
                "excluded_slugs": "retained",
            },
            notes="Turn 4 is well within the 12-message/6-exchange Redis history window (this "
            "is turn 4 of 4) - a real test of short-range carry-forward, not the structural "
            "truncation MEM-003 deliberately tests instead.",
        ),
    ],
)

c(
    "MEM-003",
    "holdout",
    "memory",
    [
        t(
            "já fui a Tóquio, não quero repetir",
            language="pt",
            expected_state={"excluded_slugs": ["toquio-jp"]},
        ),
        t("adoro cultura e história", language="pt", notes="filler turn 2"),
        t("também gosto de boa comida local", language="pt", notes="filler turn 3"),
        t("prefiro lugares menos turísticos", language="pt", notes="filler turn 4"),
        t("viajo geralmente sozinho", language="pt", notes="filler turn 5"),
        t("não me importo com o clima", language="pt", notes="filler turn 6"),
        t("gosto de caminhar bastante quando viajo", language="pt", notes="filler turn 7"),
        t(
            "então, onde você recomenda?",
            language="pt",
            expected_state={"excluded_slugs": ["toquio-jp"]},
            notes="Deliberately beyond the 12-message/6-exchange Redis cap (this is turn 8 of "
            "8) - by ai.memory.MAX_HISTORY_MESSAGES's own design, turn 1's exclusion has "
            "structurally fallen out of what intent extraction can ever see again by this "
            "point. A failure here is expected to classify as LOST_CONTEXT caused by the "
            "sliding-window truncation itself, not a model-quality miss - see the "
            "architecture trace in documentation/18_CONVERSATION_EVALUATION_FRAMEWORK.md.",
        ),
    ],
)

c(
    "MEM-004",
    "dev",
    "memory",
    [
        t("quero algo bem barato", language="pt", expected_state={"max_cost_of_living": 2}),
        t("prefiro praia", language="pt", expected_state={"trip_type": "beach"}),
        t(
            "e queria que fosse na Ásia",
            language="pt",
            expected_state={"max_cost_of_living": 2, "trip_type": "beach", "continent": "asia"},
            expected_transitions={
                "max_cost_of_living": "retained",
                "trip_type": "retained",
                "continent": "added",
            },
            notes="Positive control: max_cost_of_living has a real cross-turn accumulator in "
            "production (ai.memory.get_climate_budget/update_climate_budget), so this is "
            "expected to reliably persist, unlike trip_type/country which have none.",
        ),
    ],
)

c(
    "MEM-005",
    "dev",
    "memory",
    [
        t(
            "cultura na tailandia, ja fui a chiang mai",
            language="pt",
            expected_state={
                "trip_type": "culture",
                "country": "Thailand",
                "excluded_slugs": ["chiang-mai-th"],
            },
        ),
        t("pode ser em novembro", language="pt", expected_state={"month": 11}),
        t(
            "quais lugares você sugere?",
            language="pt",
            expected_state={
                "trip_type": "culture",
                "country": "Thailand",
                "month": 11,
                "excluded_slugs": ["chiang-mai-th"],
            },
            expected_transitions={
                "trip_type": "retained",
                "country": "retained",
                "month": "retained",
                "excluded_slugs": "retained",
            },
            notes="A second, independent instance of MTT-010's finding, one exchange later "
            "(turn 3 of 3, still well within the history window) - checks whether the same "
            "country/trip_type carry-forward gap generalizes beyond the one originally-reported "
            "message.",
        ),
    ],
)

c(
    "MEM-006",
    "dev",
    "memory",
    [
        t("I've already been to Tokyo.", expected_state={"excluded_slugs": ["toquio-jp"]}),
        t("I want a city trip.", expected_state={"trip_type": "city"}),
        t(
            "Okay, where should I go?",
            expected_state={"trip_type": "city", "excluded_slugs": ["toquio-jp"]},
            expected_transitions={"trip_type": "retained", "excluded_slugs": "retained"},
            notes="English near-verbatim of the Cycle 2 brief's own memory example, within the "
            "history window.",
        ),
    ],
)

c(
    "MEM-007",
    "dev",
    "memory",
    [
        t(
            "quero praia e orçamento bem baixo",
            language="pt",
            expected_state={"trip_type": "beach", "max_cost_of_living": 2},
        ),
        t(
            "pensando melhor, prefiro cidade mesmo",
            language="pt",
            expected_state={"trip_type": "city", "max_cost_of_living": 2},
            expected_transitions={"trip_type": "superseded", "max_cost_of_living": "retained"},
            notes="Mixed case, explicitly requested by the brief: trip_type is intentionally "
            "superseded while max_cost_of_living (accumulator-backed) should keep persisting - "
            "not everything in a conversation should carry forward the same way.",
        ),
        t(
            "e tem que ser na América do Sul",
            language="pt",
            expected_state={
                "trip_type": "city",
                "max_cost_of_living": 2,
                "continent": "south_america",
            },
            expected_transitions={
                "trip_type": "retained",
                "max_cost_of_living": "retained",
                "continent": "added",
            },
        ),
    ],
)


# ============================================================
# F. IRRELEVANT INFORMATION - conversational noise that must not perturb
# structured travel state. ~7 conversations.
# ============================================================

c(
    "IRR-001",
    "dev",
    "irrelevant_info",
    [
        t(
            "quero uma praia bem barata na Tailândia",
            language="pt",
            expected_state={"trip_type": "beach", "country": "Thailand"},
        ),
        t(
            "minha esposa se chama Ana, a propósito",
            language="pt",
            expected_state={"trip_type": "beach", "country": "Thailand"},
            expected_transitions={"trip_type": "retained", "country": "retained"},
            notes="A spouse's name is not travel-relevant signal - state must not move.",
        ),
    ],
)

c(
    "IRR-002",
    "dev",
    "irrelevant_info",
    [
        t(
            "quero conhecer cidades culturais no Japão",
            language="pt",
            expected_state={"trip_type": "culture", "country": "Japan"},
        ),
        t(
            "acabei de comprar uma mala nova, aliás",
            language="pt",
            expected_state={"trip_type": "culture", "country": "Japan"},
            expected_transitions={"trip_type": "retained", "country": "retained"},
        ),
    ],
)

c(
    "IRR-003",
    "dev",
    "irrelevant_info",
    [
        t(
            "quero uma viagem de natureza barata",
            language="pt",
            expected_state={"trip_type": "nature", "max_cost_of_living": 2},
        ),
        t(
            "nosso cachorro é enorme, mas vai ficar em casa",
            language="pt",
            expected_state={"trip_type": "nature", "max_cost_of_living": 2},
            expected_transitions={"trip_type": "retained", "max_cost_of_living": "retained"},
        ),
    ],
)

c(
    "IRR-004",
    "dev",
    "irrelevant_info",
    [
        t(
            "quero uma praia em Portugal",
            language="pt",
            expected_state={"trip_type": "beach", "country": "Portugal"},
        ),
        t(
            "eu odeio segunda-feira de manhã, sinceramente",
            language="pt",
            expected_state={"trip_type": "beach", "country": "Portugal"},
            expected_transitions={"trip_type": "retained", "country": "retained"},
        ),
    ],
)

c(
    "IRR-005",
    "holdout",
    "irrelevant_info",
    [
        t(
            "I want a cultural trip to Italy.",
            expected_state={"trip_type": "culture", "country": "Italy"},
        ),
        t(
            "By the way, my flight has a layover in Frankfurt.",
            expected_state={"trip_type": "culture", "country": "Italy"},
            expected_transitions={"trip_type": "retained", "country": "retained"},
        ),
        t(
            "Also I just adopted a cat.",
            expected_state={"trip_type": "culture", "country": "Italy"},
            expected_transitions={"trip_type": "retained", "country": "retained"},
        ),
    ],
)

c(
    "IRR-006",
    "dev",
    "irrelevant_info",
    [
        t(
            "quero uma praia bem barata em novembro",
            language="pt",
            expected_state={"trip_type": "beach", "max_cost_of_living": 2, "month": 11},
        ),
        t(
            "meu chefe está de férias essa semana, então estou meio livre para planejar",
            language="pt",
            expected_state={"trip_type": "beach", "max_cost_of_living": 2, "month": 11},
            expected_transitions={
                "trip_type": "retained",
                "max_cost_of_living": "retained",
                "month": "retained",
            },
            notes="Also checks that the destination candidate set itself doesn't reorder - the "
            "runner's ranking-independence check applies on the final turn regardless.",
        ),
    ],
)

c(
    "IRR-007",
    "dev",
    "irrelevant_info",
    [
        t(
            "quero cultura na América do Sul",
            language="pt",
            expected_state={"trip_type": "culture", "continent": "south_america"},
        ),
        t(
            "minha mãe sempre quis conhecer o Peru, mas essa viagem é só minha mesmo",
            language="pt",
            expected_state={"trip_type": "culture", "continent": "south_america"},
            expected_transitions={"trip_type": "retained", "continent": "retained"},
            notes="Mentions a real country name (Peru) purely as an aside about someone else's "
            "wish, not the traveler's own destination - state must not shift to it.",
        ),
    ],
)


# ============================================================
# CROSS-FAMILY - several phenomena in one realistic conversation.
# ============================================================

c(
    "XFAM-001",
    "dev",
    "cross_family",
    [
        t(
            "quero uma praia bem barata em novembro",
            language="pt",
            expected_state={"trip_type": "beach", "max_cost_of_living": 2, "month": 11},
        ),
        t(
            "minha esposa se chama Ana e nosso cachorro é enorme, mas ele fica com meus pais",
            language="pt",
            expected_state={"trip_type": "beach", "max_cost_of_living": 2, "month": 11},
            expected_transitions={
                "trip_type": "retained",
                "max_cost_of_living": "retained",
                "month": "retained",
            },
        ),
        t(
            "na verdade, corrigindo, o orçamento pode ser um pouco mais confortável",
            language="pt",
            expected_state={"max_cost_of_living": None},
            expected_transitions={"max_cost_of_living": "superseded"},
        ),
        t(
            "me fala mais sobre a segunda opção",
            language="pt",
            references_turn_index=0,
            references_ordinal=2,
        ),
        t(
            "já fomos para Cancún ano passado, não quero repetir",
            language="pt",
            expected_state={"excluded_slugs": ["cancun-mx"]},
        ),
        t(
            "e pensando bem, prefiro um lugar mais frio, tipo natureza nas montanhas",
            language="pt",
            expected_state={
                "trip_type": "nature",
                "min_temp_c": None,
                "max_temp_c": 15,
                "excluded_slugs": ["cancun-mx"],
            },
            expected_transitions={
                "trip_type": "superseded",
                "max_temp_c": "added",
                "excluded_slugs": "retained",
            },
            notes="The 8-turn shape from the Cycle 2 brief, compressed to 6 real turns: initial "
            "preferences, irrelevant info, budget correction, reference, exclusion, and a final "
            "climate+trip_type change - checking the exclusion from turn 5 survives the turn-6 "
            "pivot.",
        ),
    ],
    notes="Real travelers don't exhibit one failure category at a time - mirrors the exact "
    "8-turn shape requested in the Cycle 2 brief.",
)

c(
    "XFAM-002",
    "dev",
    "cross_family",
    [
        t(
            "quero cultura na Europa",
            language="pt",
            expected_state={"trip_type": "culture", "continent": "europe"},
        ),
        t("já fomos a Roma", language="pt", expected_state={"excluded_slugs": ["roma-it"]}),
        t(
            "aliás, meu sobrenome é Ferreira",
            language="pt",
            expected_state={
                "trip_type": "culture",
                "continent": "europe",
                "excluded_slugs": ["roma-it"],
            },
            expected_transitions={
                "trip_type": "retained",
                "continent": "retained",
                "excluded_slugs": "retained",
            },
        ),
        t(
            "na verdade, pensando bem, quero ficar na Ásia mesmo",
            language="pt",
            expected_state={"continent": "asia", "excluded_slugs": ["roma-it"]},
            expected_transitions={"continent": "superseded", "excluded_slugs": "retained"},
            notes="Continent contradiction combined with irrelevant info and an earlier "
            "exclusion that should survive the continent switch even though Rome is no longer "
            "geographically reachable anyway.",
        ),
    ],
)

c(
    "XFAM-003",
    "holdout",
    "cross_family",
    [
        t(
            "I want a beach trip, budget around moderate.",
            expected_state={"trip_type": "beach", "max_cost_of_living": 4},
        ),
        t(
            "Sorry, I meant affordable, not moderate.",
            expected_state={"max_cost_of_living": 3},
            expected_transitions={"max_cost_of_living": "superseded"},
        ),
        t("We've been to Cancun before.", expected_state={"excluded_slugs": ["cancun-mx"]}),
        t(
            "Actually, let's switch to a city trip instead.",
            expected_state={
                "trip_type": "city",
                "max_cost_of_living": 3,
                "excluded_slugs": ["cancun-mx"],
            },
            expected_transitions={
                "trip_type": "superseded",
                "max_cost_of_living": "retained",
                "excluded_slugs": "retained",
            },
        ),
    ],
)

c(
    "XFAM-004",
    "dev",
    "cross_family",
    [
        t("quero uma viagem de natureza", language="pt", expected_state={"trip_type": "nature"}),
        t(
            "adoro fotografia de paisagem, é meu hobby",
            language="pt",
            expected_state={"trip_type": "nature"},
            expected_transitions={"trip_type": "retained"},
        ),
        t(
            "me conta mais sobre a primeira opção",
            language="pt",
            references_turn_index=0,
            references_ordinal=1,
        ),
        t(
            "já fui pra Foz do Iguaçu esse ano",
            language="pt",
            expected_state={"trip_type": "nature", "excluded_slugs": ["foz-do-iguacu-br"]},
            expected_transitions={"trip_type": "retained", "excluded_slugs": "added"},
        ),
    ],
)

c(
    "XFAM-005",
    "dev",
    "cross_family",
    [
        t("quero cidade e cultura no México", language="pt", expected_state={"country": "Mexico"}),
        t(
            "orçamento de 800 euros no total",
            language="pt",
            expected_state={"country": "Mexico"},
            expected_transitions={"country": "retained"},
        ),
        t(
            "desculpa, quis dizer por pessoa",
            language="pt",
            expected_state={"country": "Mexico", "max_cost_of_living": None},
            notes="Combines the known currency-amount schema gap (CORR-003) with a country "
            "field that should keep persisting regardless.",
        ),
        t(
            "já fomos à Cidade do México",
            language="pt",
            expected_state={"country": "Mexico", "excluded_slugs": ["cidade-do-mexico-mx"]},
            expected_transitions={"country": "retained", "excluded_slugs": "added"},
        ),
    ],
)

c(
    "XFAM-006",
    "dev",
    "cross_family",
    [
        t(
            "Quero praia e calor.",
            language="pt",
            expected_state={"trip_type": "beach", "min_temp_c": 28},
        ),
        t(
            "Actually, no beach - we'd rather explore cities.",
            language="en",
            expected_state={"trip_type": "city", "min_temp_c": 28},
            expected_transitions={"trip_type": "superseded", "min_temp_c": "retained"},
            notes="PT -> EN language switch mid-conversation - the drift must resolve the same "
            "way regardless of which language carried it.",
        ),
    ],
    notes="Multilingual continuity (PT->EN) combined with a drift.",
)

c(
    "XFAM-007",
    "holdout",
    "cross_family",
    [
        t(
            "I want somewhere cheap for a beach vacation.",
            expected_state={"trip_type": "beach", "max_cost_of_living": 2},
        ),
        t(
            "Na verdade, prefiro um lugar de cultura mesmo.",
            language="pt",
            expected_state={"trip_type": "culture", "max_cost_of_living": 2},
            expected_transitions={"trip_type": "superseded", "max_cost_of_living": "retained"},
            notes="EN -> PT language switch mid-conversation, mirroring XFAM-006 in the other "
            "direction.",
        ),
    ],
)


# ============================================================
# METAMORPHIC pairs - two otherwise-identical conversations that should
# produce equivalent final structured state. A modest number, per the
# brief's own "high-value paired conversations" framing.
# ============================================================

c(
    "CMET-001a",
    "dev",
    "irrelevant_info",
    [
        t(
            "quero uma praia barata na Grécia",
            language="pt",
            expected_state={"trip_type": "beach", "max_cost_of_living": 2, "country": "Greece"},
        ),
        t(
            "quais lugares você recomenda?",
            language="pt",
            expected_state={"trip_type": "beach", "max_cost_of_living": 2, "country": "Greece"},
        ),
    ],
    metamorphic_pair="CMET-001",
    metamorphic_axis="irrelevant_info_equivalence",
    notes="Baseline half of a pair - no irrelevant sentence injected.",
)

c(
    "CMET-001b",
    "dev",
    "irrelevant_info",
    [
        t(
            "quero uma praia barata na Grécia",
            language="pt",
            expected_state={"trip_type": "beach", "max_cost_of_living": 2, "country": "Greece"},
        ),
        t(
            "ah, e meu irmão vem junto dessa vez",
            language="pt",
            expected_state={"trip_type": "beach", "max_cost_of_living": 2, "country": "Greece"},
            expected_transitions={
                "trip_type": "retained",
                "max_cost_of_living": "retained",
                "country": "retained",
            },
        ),
        t(
            "quais lugares você recomenda?",
            language="pt",
            expected_state={"trip_type": "beach", "max_cost_of_living": 2, "country": "Greece"},
        ),
    ],
    metamorphic_pair="CMET-001",
    metamorphic_axis="irrelevant_info_equivalence",
    notes="Same conversation plus one irrelevant sentence - final structured state should be "
    "equivalent to CMET-001a's.",
)

c(
    "CMET-002a",
    "dev",
    "correction",
    [
        t(
            "quero uma praia com orçamento moderado",
            language="pt",
            expected_state={"trip_type": "beach", "max_cost_of_living": 4},
        ),
        t(
            "quais lugares se encaixam?",
            language="pt",
            expected_state={"trip_type": "beach", "max_cost_of_living": 4},
        ),
    ],
    metamorphic_pair="CMET-002",
    metamorphic_axis="budget_correction_upward",
    notes="Baseline half - budget stated once, never corrected.",
)

c(
    "CMET-002b",
    "dev",
    "correction",
    [
        t(
            "quero uma praia bem barata",
            language="pt",
            expected_state={"trip_type": "beach", "max_cost_of_living": 2},
        ),
        t(
            "na verdade, corrigindo, pode ser orçamento moderado",
            language="pt",
            expected_state={"max_cost_of_living": 4},
            expected_transitions={"max_cost_of_living": "superseded"},
        ),
        t(
            "quais lugares se encaixam?",
            language="pt",
            expected_state={"trip_type": "beach", "max_cost_of_living": 4},
        ),
    ],
    metamorphic_pair="CMET-002",
    metamorphic_axis="budget_correction_upward",
    notes="Budget corrected upward from cheap to moderate - final state should converge with "
    "CMET-002a's (max_cost_of_living=4), and the real DB-level eligible set can only grow, "
    "never shrink, per the same cost_of_living__lte monotonicity already proven for the "
    "single-request corpus's metamorphic tests.",
)


if __name__ == "__main__":
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for conversation in _conversations:
            f.write(json.dumps(conversation, ensure_ascii=False) + "\n")
    print(f"Wrote {len(_conversations)} conversations to {OUTPUT_PATH}")
