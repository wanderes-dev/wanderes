# Multi-Turn Conversation Evaluation Framework — Wanderes

## 1. Relationship to the single-request framework

`17_EVALUATION_FRAMEWORK.md` answers "given one message, does Wanderes produce a sound recommendation." This document answers a different, independent question: **across a real conversation, does Wanderes keep a coherent, current understanding of the traveler** — preference drift, corrections, contradictions, references to what was already shown, long-range memory, and resistance to conversational noise. Neither framework modifies the other's corpus, code, or historical runs. The single-request 150-scenario corpus (`evaluations/corpus/scenarios.jsonl`) stays frozen as the reference for single-request quality (currently `92.0%`, `evaluations/runs/20260928-110009_cycle1_reference_candidate/`) - this document's own corpus never touches it.

## 2. Production architecture this framework exercises

Traced directly from `ai/views.py`, `ai/orchestration.py`, and `ai/memory.py` before any code was written here:

- **History representation**: a flat list of `{role, content}` dicts. Two backends - Redis (`ai.memory`, anonymous/normal-session chat), hard-capped at `MAX_HISTORY_MESSAGES = 12` (6 exchanges), 30-minute TTL; or Postgres (`ai.conversations.SavedConversation.messages`, opt-in authenticated saves), sliced to the same last-12 window when read.
- **What reaches the LLM**: the same raw last-12-message list on nearly every call. The isolated climate/budget-signal call is the one exception, deliberately given no history at all. Intent extraction gets a version with literal `°C`/`N/5` figures stripped from assistant turns (`_sanitized_history_messages`); everything else (including recall) sees the original.
- **Structured persistence across turns**: only `min_temp_c`/`max_temp_c`/`max_cost_of_living` have a real accumulator (`ai.memory.get_climate_budget`/`update_climate_budget`, "last non-null wins"). Every other field - `trip_type`, `continent`, `country`, `excluded_place_names`, every intent flag - is re-extracted from scratch every turn, with no persistent structured state; carry-forward depends entirely on the model re-reading raw prior text within the 12-message window.
- **Corrections**: reliable only for climate/budget (the accumulator). Nothing else has an explicit "newer statement wins" mechanism.
- **Exclusions**: re-extracted fresh every turn from raw history text, no dedup/accumulator.
- **Recommendation candidates**: never persisted as structured state anywhere. `is_recall_request` (the closest analog) works by handing the model raw history text and asking it to restate what it already said - no database re-query.
- **Reference resolution ("the second option")**: no dedicated mechanism exists. The only structured way to act on a specific shown destination is `focus_destination_slug` (the "Choose this trip" button), which is a real catalog slug the client already knows and posts directly - it bypasses intent extraction entirely and has nothing to do with parsing an ordinal reference from typed text.
- **`TravelerProfile` relationship**: one-directional, mostly static - feeds prompts as background context for authenticated users; nothing from a live conversation writes back mid-conversation.
- **Real production code path**: `ai/views.py`'s chat handler calls `stream_travel_recommendation(message, user=, session_key=, history_override=)`. `history_override` is used **only** when resuming a specific `SavedConversation`; it forces `conv_key = None`, skipping the Redis persistence layer (the climate/budget accumulator, the profile-confirmation gate) entirely. The normal path uses `session_key=` and the real `conv_key`.

**Two load-bearing facts found while tracing this, directly shaping the corpus:**

- The 12-message/6-exchange cap is a **hard, deterministic truncation**, not an LLM inconsistency - a scenario whose relevant gap exceeds ~6 exchanges is structurally guaranteed to lose the earlier fact, a different root cause from "the model saw it and forgot."
- `max_cost_of_living` extraction recognizes only qualitative words ("cheap"/"affordable"/"moderate"/"luxury") - there is no anchor mapping a literal currency figure ("€800", "€1,500") to the 1-5 tier at all (checked directly against `CLIMATE_BUDGET_SYSTEM_PROMPT`).

## 3. Why this corpus drives the real production path, not a simplified imitation

Cycle 1's evaluator always calls `stream_travel_recommendation` with `history_override=`, which - per §2 above - never exercises the real Redis-backed `conv_key` at all. That's fine for a single-request question ("is this one extraction correct"), but it would silently defeat the entire point of a conversation corpus, since the climate/budget accumulator and the profile-confirmation gate are exactly two of the pieces of real persistent state this corpus needs to measure.

`evaluations.conversation_runner.run_conversation` therefore drives every turn via `session_key=<per-conversation synthetic key>` (never `history_override=`), calling `memory.clear_history()` before the first turn so no state leaks from a prior attempt or a previous run. This is the same entry point, the same intent extraction, the same scoring, the same explanation generation a real `/chat/` request uses - no special evaluation-only conversation engine exists.

**Two paths (Improvement 4).** That default ("direct") path is the path an anonymous visitor, or the first turn of any conversation, takes. A signed-in traveler who leaves "Save this conversation" on (the default) takes a different one from turn 2 on: the view hands the orchestration a `history_override` plus a `thread_id`, and whether the accumulated state carries over is decided by state *ownership* (see the Improvement 4 entry in `DEVELOPMENT_LOG.md`). The direct path cannot see that handoff, so the runner has a second mode, `path="view"` (`evaluate_conversations --path view`, implemented in `evaluations/view_path.py`): every turn is a POST to the real `/api/v1/recommendations/` endpoint as a signed-in synthetic account with saving on, the saved conversation's id is picked up from the response footer and sent back from turn 2 on - exactly as the chat page's JS does. Only two things are patched: the view's call into the orchestration (wrapped, so the evaluation can hand in its providers and read `intent_sink`/`state_sink` back) and the provider that titles a new saved conversation (so a run pays for no call it doesn't otherwise make). Each run's `meta.json` records its `path` (runs before this field existed were all `direct`). **The view path has been proven with scripted providers only; it has not yet been run against the real model** - a first real run is the intended baseline-then-compare step, and its numbers are not comparable with `direct` runs until that comparison is made.

## 4. Conversation schema

`evaluations/conversation_scenarios.py`:

- `ConversationTurn`: `message`, `language`, `expected_state` (a partial dict using the real `RecommendationRequest` field names - `month`/`min_temp_c`/`max_temp_c`/`max_cost_of_living`/`trip_type`/`continent`/`country`/`excluded_slugs` - never an invented schema), `expected_transitions` (doc-only, field -> retained/added/superseded/removed/unresolved), `references_turn_index`/`references_ordinal` (for Family D, resolved against the referenced turn's **actual recorded** scored list at run time, never a pre-authored assumption), `expects_clarification`.
- `ConversationScenario`: `id`, `split`, `family`, `turns` (2-12), `profile_overrides`, `metamorphic_pair`/`metamorphic_axis`.
- An omitted `expected_state` field means "not checked at this checkpoint" (same convention as `evaluations.scenarios`'s `expected_intent`); an explicit `None` means "expected null right now" - this is how supersession/removal get asserted without a separate mechanism.

## 5. Corpus

`evaluations/corpus/conversations.jsonl`, built by `evaluations/corpus/build_conversation_corpus.py` - a separate file and a separate builder from Cycle 1's; neither is modified by the other.

- **53 conversations** (target was ~72; scoped down for genuine hand-authored quality within this cycle's available time - see §14). 45 dev / 8 holdout (84.9%/15.1%, deterministic - `split` is authored directly per conversation, same convention as Cycle 1's own hash-free authored split).
- **Family distribution**: drift 7, correction 9 (7 authored + 2 as one metamorphic pair's baseline/variant), contradiction 7, reference 7, memory 7, irrelevant_info 9 (7 authored + 2 metamorphic), cross_family 7.
- **Turns**: min 2, max 8, average 2.6. Skews shorter than the "roughly 3-10" guidance - correction/contradiction/drift are genuinely 2-turn phenomena by nature (the brief's own "€800 total" -> "sorry, per person" example is 2 turns), while cross-family and memory conversations run 4-8 turns.
- **Every destination/country/trip_type/cost_of_living fact** was checked directly against `travel/data/curated_destinations.json`, through the same Portuguese-label-first-segment mapping `load_destinations.py` applies (the raw dataset's `trip_type` field is still "Cultura/história"-style text).
- **`MEM-001`** ports Cycle 1.6's `MTT-010` finding verbatim as its first turn, per direct instruction - not fixed here.
- **2 metamorphic pairs**: `CMET-001` (identical conversation vs. + one irrelevant sentence, expecting equivalent final state) and `CMET-002` (budget never corrected vs. corrected upward, expecting the eligible set to only grow, mirroring the single-request corpus's own proven `cost_of_living__lte` monotonicity).
- **Multilingual continuity**: `XFAM-006` (PT->EN) and `XFAM-007` (EN->PT) switch language mid-conversation; several other conversations are PT-only or EN-only for variety.
- **Currency-amount gap documented, not chased**: `CORR-003` and `XFAM-005` deliberately use literal euro amounts specifically to record the real schema gap found in §2 (`max_cost_of_living=None` expected both before and after the "correction," since neither a literal total nor a per-person figure has an extraction anchor today).

## 6. Execution and checks

- **No deterministic-only mode.** Unlike the single-request framework, a conversation's whole point is whether state persists through real, live extraction - there is no zero-cost mode that would mean anything here. `--dry-run` estimates calls/cost without spending anything.
- **Checkpoint comparison** (`evaluations.conversation_invariants.evaluate_checkpoint`) reuses `evaluations.intent_eval`'s own `_values_match` field-comparison semantics directly, so a float/list/None comparison behaves identically to the single-request corpus.
- **What a checkpoint reads as the "actual state"** (`evaluations.conversation_invariants.build_actual_state`): the accumulated state as it is *persisted* after the turn - `stream_travel_recommendation`'s `state_sink`, recorded per turn as `TurnResult.effective_state` - for the seven accumulator fields (`min_temp_c`, `max_temp_c`, `max_cost_of_living`, `trip_type`, `continent`, `country`, exclusions). It is deliberately not the turn's own extraction (`intent_sink`, recorded as `TurnResult.intent`, unchanged): a turn that returns before the accumulator merge (small talk, a stated future trip, a visa question...) yields an extraction that says nothing about what the conversation holds. `month` is not part of the persisted state, so it is still read from the turn's own extraction. **Runs made before this change (through `conversation_cycle1_fix`) read the raw extraction, so their per-turn state-retention numbers are not directly comparable with later ones** - see the Improvement 2 entry in `DEVELOPMENT_LOG.md` for the same run scored both ways.
- **Stale-state vs. lost-context classification** (`classify_checkpoint_mismatch`): for a failed checkpoint field, compares the wrong actual value against the conversation's own earlier checkpoints - if it matches a value from *before* an authored supersession, it's `STALE_STATE`; if a real, unsuperseded earlier value reverted to null, it's `LOST_CONTEXT`; otherwise a plain checkpoint mismatch, bucketed by family (`CORRECTION_FAILURE`/`CONTRADICTION_RESOLUTION`) as a fallback.
- **Exclusion persistence**: a slug asserted excluded at one checkpoint must still be excluded at every later excluded_slugs-checking checkpoint, unless the corpus explicitly authors a reversal.
- **Reference resolution**: resolves "the Nth option" against the referenced turn's real recorded `scored` list at run time, then checks the later turn's reply actually mentions that real destination (reusing `evaluations.destination_equivalence.mentions_destination` - the same diacritic-normalization/exonym-table matching the single-request corpus's `winner_mentioned` check already relies on).
- **Grounding and ranking independence**: the single-request framework's own `run_grounding_checks` and `check_no_affiliate_or_acquisition_signal_in_scoring` are reused as-is on the conversation's final turn - never duplicated.
- **Cost tracking**: `evaluations.cost.CostTracker` is reused per-turn rather than per-scenario (a conversation is just N sequential pipeline calls).

## 7. Taxonomy

`evaluations.taxonomy.FailureCategory` gained six categories for this cycle: `LOST_CONTEXT`, `STALE_STATE`, `CORRECTION_FAILURE`, `CONTRADICTION_RESOLUTION`, `REFERENCE_RESOLUTION`, `EXCLUSION_PERSISTENCE` - added to the existing enum (not a separate one), so there is exactly one taxonomy for the whole evaluation surface. `checkpoint_state:<field>` is deliberately **not** in the static name->category table (`_CHECK_CATEGORY`) - its category depends on comparing against the conversation's own earlier checkpoints, which only `evaluations.conversation_persistence._checkpoint_taxonomy_category` has the context to resolve; every other check name (grounding, ranking-independence, `reference_resolved`, `exclusion_still_persists`, `dependency_failure`) resolves through the shared static table exactly like the single-request corpus's own checks do.

## 8. Metrics

Deliberately kept separate and interpretable, never collapsed into one score (`evaluations.conversation_persistence.save_conversation_run`):

- `checkpoint_pass_rate` - overall, across every checkpoint in every evaluable conversation.
- `retained_field_accuracy` - of every checkpoint field asserted non-null (should still be true), how often it actually matched.
- `correction_accuracy` / `contradiction_resolution_accuracy` / `irrelevant_information_stability` - checkpoint pass rate restricted to conversations in that family.
- `supersession_accuracy` - restricted to checkpoint fields an authored `expected_transitions` marks `superseded`/`removed` at that turn.
- `exclusion_persistence_accuracy` - of every (conversation, slug-still-expected-excluded) assertion, how many held.
- `reference_resolution_accuracy` - of every reference turn where the referenced turn actually produced enough options to resolve (a corpus-side "too few options" case is excluded from the denominator, not scored as a failure), how often the reply engaged with the real resolved destination.
- Full/checkpoint results are reported by split and by family, denominators always visible.

## 9. Known limitations - stated honestly, matching §18 of the single-request framework doc

- **53 conversations, not ~72.** Scoped down for genuine, hand-checked quality within this cycle's time - every conversation was individually authored and fact-checked against the real catalog, not templated or generated in bulk. Extending the corpus (more conversations per family, deeper cross-family chains) is a natural, low-risk follow-up - the framework itself doesn't need to change to grow it.
- **`checkpoint_state` comparisons only cover the fields present in each turn's `expected_state`** - a field genuinely worth checking but omitted from a given checkpoint (because the corpus author didn't think to assert it) is silently not evaluated, same convention and same limitation as the single-request corpus's `expected_intent`.
- **Reference resolution can only be evaluated when the referenced turn actually produced a scored candidate at that ordinal position** - a turn that produced fewer options than an authored ordinal expects (`REF-004`'s deliberately ambiguous "the other two," or any turn that fell into a non-scoring branch) is excluded from the denominator, not penalized - this is a corpus-design choice, not a claim that the underlying feature works.
- **The accumulator/no-accumulator asymmetry means "retained-field accuracy" partly measures a known-different mechanism per field** - climate/budget fields are backed by a real accumulator and expected to score very differently from trip_type/country/continent/exclusions, which have none. The per-family and per-field breakdowns exist specifically so this doesn't get smoothed into one misleading aggregate.
- **`checkpoint_state:<field>`'s stale/lost classification is heuristic, not exhaustive** - it recognizes the two specific patterns named in the Cycle 2 brief (a superseded value reappearing; a real value reverting to null) by comparing against the conversation's own authored checkpoints, but a more unusual failure shape (e.g. a value jumping to something never authored at all) falls back to a family-based default category rather than a dedicated new label.
- **No live weather contamination risk**: the conversation corpus's checkpoint candidate destinations turned out to already be fully covered by the existing 4608-entry fixture (itself already the full 384-destination × 12-month catalog, a side effect of Cycle 1.6's own maximal-relaxation fix for `ROB-015`) - no additional live Open-Meteo capture was needed for this baseline.

## 10. Commands reference

```bash
# Estimate cost/calls for a selection - no AI calls made
python manage.py evaluate_conversations --split all --full --dry-run

# Run one conversation and print its full turn-by-turn trace (dev diagnostics)
python manage.py evaluate_conversations --trace MEM-001

# Run a random sample of the dev split
python manage.py evaluate_conversations --sample 5

# Run one family only
python manage.py evaluate_conversations --family reference

# Run the complete baseline (both splits)
python manage.py evaluate_conversations --split all --full --label conversation_baseline

# The same conversations through the real chat endpoint, as a signed-in traveler with
# "Save this conversation" on (the saved-conversation path; real AI cost, same as above)
python manage.py evaluate_conversations --split all --full --path view --label conversation_view

# Weather fixture coverage is shared with the single-request corpus -
# refresh_weather_fixtures already accounts for both
python manage.py refresh_weather_fixtures --dry-run
```
