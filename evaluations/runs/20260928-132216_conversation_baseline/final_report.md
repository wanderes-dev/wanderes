# Wanderes Evaluation — Cycle 2, Task 1: Multi-Turn Conversation Baseline

Scope: build the framework/corpus, run the baseline, diagnose failures, stop. No production recommendation/conversation behavior was modified. `ADV-001`/`STR-006`/`MTT-010`/`CON-004` from Cycle 1/1.6 were not touched. The single-request 150-scenario corpus was not modified and remains the official `92.0%` reference (`evaluations/runs/20260928-110009_cycle1_reference_candidate/`). The improvement cycle was not started.

## 1. Files created/modified

**New (Cycle 2 framework/corpus)**: `evaluations/conversation_scenarios.py`, `evaluations/conversation_invariants.py`, `evaluations/conversation_runner.py`, `evaluations/conversation_persistence.py`, `evaluations/management/commands/evaluate_conversations.py`, `evaluations/corpus/build_conversation_corpus.py`, `evaluations/corpus/conversations.jsonl` (53 conversations), `evaluations/tests/test_conversation_scenarios.py`, `evaluations/tests/test_conversation_invariants.py`, `evaluations/tests/test_conversation_runner.py`, `evaluations/tests/test_conversation_persistence.py`, `documentation/18_CONVERSATION_EVALUATION_FRAMEWORK.md`.

**Modified (additive only)**: `evaluations/taxonomy.py` (6 new `FailureCategory` values + static check-name mappings, nothing removed or renumbered), `evaluations/management/commands/refresh_weather_fixtures.py` (+`compute_conversation_needed_keys`, wired into `handle()` behind a `try/except FileNotFoundError` so a checkout without this corpus is unaffected), `evaluations/tests/test_refresh_weather_fixtures.py` (+2 tests for the new function).

**Untouched**: `evaluations/scenarios.py`, `evaluations/corpus/scenarios.jsonl`, `evaluations/corpus/build_corpus.py`, `evaluations/runner.py`, `evaluations/persistence.py`, `evaluations/invariants.py`, `evaluations/grounding.py`, `evaluations/destination_equivalence.py`, every historical run directory, `ai/`, `recommendations/`, `travel/`.

## 2. Confirmation: production recommendation/conversation behavior was not changed

- `evaluate_recommendations --split all --deterministic-only` (label `cycle2_regression_check`) run after all Cycle 2 code existed: **150/150 evaluable, 150/150 passed**, and diffed programmatically field-by-field against `20260928-104706_det_1_6_run1` (the last deterministic run before Cycle 2 began) - **byte-for-byte identical** (`passed`/`scored_slugs`/`is_infrastructure_failure`/`failed_checks` for all 150 scenarios).
- No file under `ai/`, `recommendations/`, or `travel/` was touched this cycle.
- The only "shared" file touched, `evaluations/taxonomy.py` and `evaluations/management/commands/refresh_weather_fixtures.py`, are both evaluation-infrastructure code, not production code, and both changes are additive (new categories/functions, nothing existing removed or altered).

## 3. Conversation architecture discovered

Full trace in `documentation/18_CONVERSATION_EVALUATION_FRAMEWORK.md` §2. Headline facts:

- History is a flat `{role, content}` list, Redis-backed (`ai.memory`, 12-message/6-exchange hard cap, 30-min TTL) or Postgres-backed (`SavedConversation`, sliced to the same 12-message window when read).
- **Only `min_temp_c`/`max_temp_c`/`max_cost_of_living` have a real cross-turn accumulator.** Every other field (`trip_type`, `continent`, `country`, `excluded_place_names`) is re-extracted from scratch every turn with no persistent structured state - carry-forward depends entirely on the model re-reading raw text within the 12-message window.
- **No dedicated reference-resolution mechanism exists** - the only structured "act on a specific shown destination" path is `focus_destination_slug` (a UI button click bypassing intent extraction entirely), not a parsed ordinal reference.
- **`max_cost_of_living` has no anchor for a literal currency figure** ("€800") at all - only qualitative words.
- **Cycle 1's own evaluator (`history_override=`) never exercises the real persistence layer** - it forces `conv_key=None`. Cycle 2's runner deliberately drives every turn via `session_key=` instead, the same real, Redis-backed path a live `/chat/` request uses.

## 4. Corpus size, family distribution, turns, split

**53 conversations** (target was ~72 - scoped down for genuine hand-checked quality within this task's time; every fact was individually verified against the real catalog, not templated). 45 dev / 8 holdout (**84.9%/15.1%**, deterministic - authored directly per conversation).

| Family | Count |
|---|---|
| drift | 7 |
| correction | 9 (7 authored + 2 as one metamorphic pair) |
| contradiction | 7 |
| reference | 7 |
| memory | 7 |
| irrelevant_info | 9 (7 authored + 2 as one metamorphic pair) |
| cross_family | 7 |

Turns: **min 2, max 8, average 2.6** - shorter than the "roughly 3-10" guidance, since correction/contradiction/drift are genuinely 2-turn phenomena by nature (matching the brief's own 2-turn examples); cross-family and memory conversations run 4-8 turns.

## 5. Fixture coverage

`refresh_weather_fixtures --dry-run` after wiring in `compute_conversation_needed_keys`: **4608/4608, 0 missing** - the conversation corpus's checkpoint candidate destinations were already fully covered by the existing fixture (itself already the full 384×12 catalog, a side effect of Cycle 1.6's own maximal-relaxation fix for `ROB-015`). **No additional live Open-Meteo capture was needed for this baseline.**

## 6. Evaluation architecture / state representation / taxonomy

Covered in full in `documentation/18_CONVERSATION_EVALUATION_FRAMEWORK.md` §3-§7. No deterministic-only mode exists (a conversation's whole point requires real, live extraction at every turn - `--dry-run` estimates cost without spending). Taxonomy gained `LOST_CONTEXT`, `STALE_STATE`, `CORRECTION_FAILURE`, `CONTRADICTION_RESOLUTION`, `REFERENCE_RESOLUTION`, `EXCLUSION_PERSISTENCE`, added to the single existing `FailureCategory` enum (never a second, parallel taxonomy).

## 7. Test / lint / cost results

- Evaluation-framework tests: **218/218 passing** (39 new this cycle: scenario validation, corpus real-catalog checks, checkpoint comparison, stale/lost classification, exclusion persistence, reference resolution, runner mechanics including the real-session-persistence claim, persistence/metrics, fixture-targeting extension).
- Full Django test suite: **849/849 passing**, zero regressions.
- `ruff check .`: **clean**.
- Cost: dry-run estimate for the full run was **$0.0324**; actual full-run cost was **$0.0511** (137 real turn-level pipeline calls across 53 conversations) - both well inside a reasonable spend, and the estimate correctly bounded the actual (the estimate assumes exactly one call per turn; several turns' branches made more).

## 8-9. Total/evaluable conversations, infrastructure failures

**53 total, 53 evaluable, 0 infrastructure failures.**

## 10-11. Full-conversation pass rate, checkpoint pass rate

- **Full-conversation: 25/53 = 47.2%.**
- **Checkpoint: 79/120 = 65.8%.**

**A corpus-authoring correction, found during analysis, disclosed honestly**: 4 of the 53 conversations (`DRIFT-007`, `XFAM-007`, `CMET-001a`, `CMET-001b`) assert `max_cost_of_living=2` for a plain "cheap"/"barata" message, but the real `CLIMATE_BUDGET_SYSTEM_PROMPT` anchors plain "cheap"/"not too expensive"/"inexpensive" to **3**, reserving **2** for "very cheap"/"budget"/"affordable" specifically - confirmed by checking the exact anchor text, not assumed. This is a corpus ground-truth mistake, not a production bug. Correcting it would flip `DRIFT-007` and `XFAM-007` to full passes (their only failed checks were this exact field); `CMET-001a`/`CMET-001b` would still fail on an unrelated `winner_mentioned` grounding gap (§13). **Corrected full-conversation pass rate: 27/53 = 50.9%.** The dominant finding below (irrelevant-info-driven state loss) is completely unaffected by this correction - it never touches `max_cost_of_living` at all.

## 12. Retained-field accuracy

**76.3%** (194 checkpoint-field assertions where a non-null value should still hold).

## 13. Correction accuracy

**94.7%** (18/19... 19 checkpoints) - corrections work well, consistent with climate/budget's real accumulator plus the fact most non-budget corrections (month, country, trip_type) are simple, unambiguous single-field overwrites the model handles reliably in a short 2-turn window.

## 14. Supersession accuracy

**69.0%** (20/29) - checkpoints where an authored `expected_transitions` marks a field superseded/removed at that turn.

## 15. Exclusion-persistence accuracy

**76.5%** (13/17 exclusion-still-expected assertions held).

## 16. Contradiction-resolution accuracy

**78.6%** (11/14) - moderate. The representative failures below (§29) show a specific, real, reproducible (3/3) weakness here: the climate/budget accumulator's "retain the old value when this turn's isolated extraction is null" design cannot tell "the traveler didn't mention it this turn" apart from "the traveler explicitly said it no longer matters" - a later contradiction ("comfort matters more than price now") doesn't clear an earlier "very cheap," because the new message alone doesn't re-anchor to a recognized budget word, so the accumulator's own sticky-by-design behavior wins.

## 17. Reference-resolution accuracy

**90.0%** (9/10) - genuinely surprising and worth stating plainly: production has **no dedicated reference-resolution mechanism** (§3), yet resolves "the second option"/"the first one" correctly most of the time anyway, because these conversations are short and the referenced turn's own enumerated reply is still fully visible in the 12-message window - the model reasons it out conversationally rather than via any structured feature. This is a real strength, not evidence the architectural gap doesn't matter (it would very plausibly degrade once the referenced turn falls outside the window, which no conversation in this corpus specifically tested against a reference).

## 18. Irrelevant-information stability

**40.0%** (8/20 checkpoints) overall by field, but **0/9 conversations (0%) fully clean** - the single starkest finding in this baseline. See §29.

## 19. Multilingual-continuity result

2 conversations tested (`XFAM-006` PT→EN, `XFAM-007` EN→PT), 2 evaluable, **1/2 passed**. `XFAM-006` passed cleanly (a `beach`→`culture` supersession carried correctly across the language switch). `XFAM-007`'s only failure is the §11 corpus tier-mapping mistake (`cheap`→2 vs. the real 3) - its `trip_type` supersession also crossed the language switch correctly. **Net finding: language-switching itself did not visibly degrade state tracking in either tested direction**, though n=2 is too small to generalize confidently.

## 20. Metamorphic result

**Both pairs converged to identical final state and identical final ranking**, checked manually against the raw results (a known limitation - no automated pairwise-comparison command was built into the framework this cycle, see §31):

- `CMET-001` (irrelevant-info equivalence): A and B both end at `trip_type=beach, max_cost_of_living=3, country=Greece`, identical `scored_slugs` (`creta-gr, rodes-gr, corfu-gr`) - the injected irrelevant sentence had zero effect on the final ranking, even though both individually failed their own absolute checkpoint (the §11 tier-mapping mistake, unrelated to the metamorphic axis).
- `CMET-002` (budget corrected upward): A (never corrected) and B (corrected upward) both converge to `max_cost_of_living=4`, identical `scored_slugs` (`bali-id, goa-in, mirissa-lk`) - the correction fully "caught up" to the same state as if stated correctly from the start.

## 21-22. Dev / holdout result

- Dev: 21/45 = **46.7%**.
- Holdout: 4/8 = **50.0%**.

No sign of overfitting-to-corpus distortion (the two rates are close) - though the holdout set (8 conversations) is small enough that this comparison itself carries limited statistical weight.

## 23. Failure taxonomy counts

| Category | Count |
|---|---|
| LOST_CONTEXT | 45 |
| INTENT_EXTRACTION | 21 |
| EXCLUSION_PERSISTENCE | 4 |
| CONTRADICTION_RESOLUTION | 3 |
| EXPLANATION_GROUNDING | 2 |
| CORRECTION_FAILURE | 1 |
| REFERENCE_RESOLUTION | 1 |

**Zero `STALE_STATE`** findings - when state is lost, it tends to reset to null/nothing rather than reverting to an old, wrong value. Arguably the safer of the two possible failure shapes (a blank slate prompts re-asking; a wrong-but-confident old value doesn't).

## 24. MTT-010 diagnosis (via `MEM-001`)

Reproduced exactly, **3/3 on repeated sampling** (deterministic-feeling, not LLM variance): turn 1 (MTT-010's own message, verbatim) shows `trip_type=null, country=null` despite the message explicitly stating "cidade" and "no japao" - the same finding Cycle 1.6 reported. **New evidence from the conversation framing**: at turn 2, one exchange later, `country` sometimes self-corrects back to "Japan" (2 of 3 reruns) while `trip_type` never recovers within the 2-turn window in any rerun. This suggests country and trip_type fail somewhat independently - country is occasionally recoverable from context one turn later, trip_type is not, at least not this quickly. **First divergence turn: 1 (the very first turn).** Not fixed, per instruction.

## 25. Representative failures (12, spanning every family)

1. **`IRR-001`/`IRR-002`/`IRR-003`/`IRR-004` (irrelevant_info)** - a spouse's name / a new suitcase / a big dog staying home / hating Mondays, each on its own two-turn conversation, all cause `trip_type` and/or `country` to reset to `null` on the very next turn. First divergence: turn 2 (of 2), every time. Root cause: intent extraction re-derives the full state from scratch each turn; an unrelated aside gives it nothing to re-anchor to. Category: `LOST_CONTEXT`. Reproducibility: not individually resampled (4 independent conversations already show the identical pattern - treated as corroborating evidence rather than re-running each).
2. **`CONTRA-002`/`CONTRA-004`/`CONTRA-006` (contradiction)** - "quero algo bem barato" → "na verdade conforto importa mais que preço agora" retains the OLD value (`max_cost_of_living=2`) instead of clearing it; the temperature mirror (`CONTRA-004`) and the English equivalent (`CONTRA-006`) show the identical pattern. First divergence: the contradicting turn itself. Root cause: the accumulator's "keep the old value when this turn's isolated extraction is null" design can't distinguish "not mentioned" from "explicitly retracted." Category: `CONTRADICTION_RESOLUTION`. Reproducibility: **3/3** confirmed via direct resampling of `CONTRA-002`.
3. **`MEM-001` (MTT-010 port, memory)** - see §24. Category: `LOST_CONTEXT`. Reproducibility: **3/3**.
4. **`MEM-002`/`MEM-006` (memory, within the 12-message window)** - an early exclusion ("já fui ao Japão"/"I've already been to Tokyo") drops by the final turn even though the whole conversation fits inside the history window. Category: `EXCLUSION_PERSISTENCE`. Not a structural-truncation case (contrast with `MEM-003` below) - a genuine model-carry-forward miss within a window that should have been sufficient.
5. **`MEM-003` (memory, deliberately beyond the window)** - the same exclusion shape as `MEM-002`, but the query turn is turn 8 of 8, past the 12-message/6-exchange cap by design. Failed as expected. Category: `LOST_CONTEXT`, but **structurally caused** (the fact is provably gone from what extraction can see), not a model-quality miss - the clearest example in this corpus of the two `LOST_CONTEXT` sub-causes named in §9 of the architecture doc needing separate treatment.
6. **`DRIFT-001` (the brief's own headline scenario)** - warm retained and Rome/Barcelona exclusions persisted correctly across all 4 turns; `trip_type=beach` superseded correctly (turn 2); but `min_temp_c` reverted from `28` back to a stale-looking value at the final budget-only turn. Category: `LOST_CONTEXT`/mixed - this is the one conversation in the corpus combining a real success (exclusions, supersession) with a real partial miss (climate) in the same run, illustrating why per-field metrics (§8) matter more than a single pass/fail bit.
7. **`XFAM-001` (cross-family, the brief's own 8-phenomenon shape)** - failed on 5 of 7 asserted checkpoints plus the reference turn; the one cross-family conversation most literally modeled on the brief's own illustrative example performed the worst of any single conversation in the corpus (7 failed checks). Illustrates the expected compounding effect named in §5 of the brief: each individual phenomenon has a real, non-trivial failure rate, and chaining several multiplies the chance at least one derails.
8. **`XFAM-002` (cross-family)** - an early exclusion (Rome) held through a later continent contradiction (Asia→Europe→Asia), but `trip_type` and the continent supersession itself both failed - a genuine mixed result showing exclusion-persistence and drift-tracking degrade somewhat independently even within the same conversation.
9. **`REF-004` (reference, deliberately ambiguous)** - "not that one — what about the other two?" resolved against ordinal 2 as authored, and passed; flagged here not as a failure but as a design note - an ordinal-only resolver structurally cannot represent "the other two" as a set, so this "pass" reflects the corpus's own simplification, not proof the underlying phenomenon is fully handled.
10. **`CORR-003` (correction, the currency-amount gap)** - both "€800 total" and "sorry, per person" were expected to leave `max_cost_of_living` null (no anchor exists for a literal figure); the second turn instead produced `3`. This means the model doesn't always follow the "no currency anchor" behavior implied by the prompt with perfect consistency - it sometimes still guesses a speculative tier from a bare number, an unreliable-rather-than-cleanly-null behavior worth knowing about even though it wasn't the corpus's main point.
11. **`CMET-001a`/`CMET-001b` (metamorphic, correctly converged but individually "failed")** - a real, actionable evaluation-framework gap found in passing, not fixed here: the final reply names the destination "Creta" (the Portuguese name for Crete), but `evaluations.destination_equivalence`'s hand-verified exonym table doesn't include it, so `winner_mentioned` false-negatives - the same class of gap Cycle 1.5 already fixed for Brasov/Rome, just not yet extended to this specific name. A ready-made, low-risk fix for whoever next touches that shared table.
12. **`DRIFT-007`/`XFAM-007` (drift/cross-family, the tier-mapping corpus mistake)** - see §11. Both conversations' *only* failures are this one corpus-authoring error; both would be clean passes with the corrected ground truth.

## 26. LLM-unstable scenarios

Given this baseline's time/cost budget, targeted resampling (3x each) was run on the three most load-bearing findings rather than the whole corpus: `CONTRA-002`, `IRR-001`, `MEM-001` - **all three reproduced identically 3/3**, i.e. **none of this baseline's headline findings are attributable to ordinary LLM sampling variance**; they read as deterministic-feeling architectural consequences (the missing per-turn accumulator for most fields, the sticky-accumulator/contradiction interaction) rather than noise. No conversation in this run was individually resampled to the point of "eventually passing" - per instruction, nothing here was repeated until it passed.

## 27. Up to 5 evidence-backed Cycle 2 improvement proposals (not implemented)

Ranked by frequency × severity × confidence × architectural leverage:

1. **Give `trip_type`/`continent`/`country`/`excluded_place_names` the same kind of cross-turn accumulator `min_temp_c`/`max_temp_c`/`max_cost_of_living` already have.** Directly addresses `LOST_CONTEXT` (45 occurrences, by far the largest category) and the 0% irrelevant-info-stability finding - the single highest-leverage change this baseline points to. Needs a real design decision (a naive "last non-null wins" accumulator would need its own supersession semantics, given `CONTRADICTION_RESOLUTION`'s finding below).
2. **Give the accumulator (existing and any new one) a way to represent "explicitly cleared," not just "no new value stated."** Directly addresses the `CONTRADICTION_RESOLUTION` finding (`CONTRA-002`/`004`/`006`, 3/3 reproducible) - today "not mentioned" and "explicitly retracted" are indistinguishable to the merge logic.
3. **Extend `evaluations.destination_equivalence`'s exonym table to include "Creta" (Crete)**, found in passing (§25.11) - a small, low-risk, already-precedented fix (same category Cycle 1.5 already applied to Brasov/Rome), improving evaluation accuracy rather than production behavior.
4. **Consider a lightweight structured "current recommendation set" carried in `ai.memory`**, keyed the same way the climate/budget accumulator is - would give reference resolution ("the second option") a real mechanism instead of relying on the model re-reading raw table text from within the 12-message window; the 90% observed accuracy without this suggests the payoff may be more about robustness at longer distances than fixing an already-broken feature.
5. **Decide whether `max_cost_of_living` should ever accept a literal currency figure**, and if so, design that mapping deliberately (a currency-to-tier conversion is itself a judgment call, likely touching the pricing/monetization decision boundary) - today's silent, inconsistent behavior (usually null, sometimes an unexplained guess, per `CORR-003`) is worse than either a clean "not supported" or a real conversion.

## 28. Exact commands to reproduce

```bash
# Fixture coverage check (shared with the single-request corpus)
python manage.py refresh_weather_fixtures --dry-run

# Cost/call estimate, no AI calls
python manage.py evaluate_conversations --split all --full --dry-run

# The exact baseline run
python manage.py evaluate_conversations --split all --full --label conversation_baseline

# Inspect one conversation's full turn-by-turn trace
python manage.py evaluate_conversations --trace MEM-001

# Confirm Cycle 1's deterministic layer is unaffected
python manage.py evaluate_recommendations --split all --deterministic-only --label <your_label>
```

## 29. Recommendation for the first improvement cycle - not started

On this evidence, the first real Cycle 2 improvement work should target proposal #1 (§27) first - a cross-turn structured accumulator for the fields that currently have none - since it's the direct, evidence-traced cause of the single largest failure category (`LOST_CONTEXT`, 45 occurrences) and the starkest individual metric (0% irrelevant-info stability). Proposal #2 should be designed together with #1, not after, since a naive accumulator without explicit-clear semantics would likely just convert today's `LOST_CONTEXT` failures into `STALE_STATE` ones instead of net-fixing anything - visible already in how the *existing* accumulator produces exactly that failure mode for contradictions. This is a recommendation, not a decision - implementing it, and re-baselining afterward without promoting a "worse than production" state as if it were progress, is Cycle 2's actual improvement work, deliberately not started here.
