# Recommendation Evaluation Framework — Wanderes

## 1. Purpose and philosophy

`13_TESTING_STRATEGY.md` §8 ("AI Evaluation") charters a "maintained set of representative scenarios" for judging recommendation quality but never built one out — evaluation stayed qualitative and ad hoc (the `testes/*.md` dated notes are the closest thing that existed before this). This document describes the framework that fills that gap: `evaluations/`, a synthetic-scenario corpus plus a runner (`python manage.py evaluate_recommendations`) that answers, repeatably and with evidence, *does Wanderes understand the traveler correctly, respect hard constraints, rank sensible destinations, explain its reasoning accurately, and avoid confidently making unsupported claims?*

Three things this framework is explicitly **not**:

- **Not a self-training or self-tuning system.** It never modifies scoring weights, destination data, prompts, or production behavior. It measures and reports; a human decides what changes.
- **Not a replacement for `pytest`.** Unit/integration tests (recommendations/tests, ai/tests, ...) verify the code does what it's supposed to, fast, with stubbed AI. This framework verifies the *product* — real destinations, optionally a real model — behaves well across a deliberately broad, realistic set of requests. Running the full corpus through the real AI pipeline is never part of the default `pytest` run (see §8, Cost controls); the framework's *own* unit tests (`evaluations/tests/`) are fast and AI-free, and those do run normally.
- **Not a golden-destination benchmark.** A scenario almost never asserts "the correct answer is Madeira." Most travel requests have several defensible answers. What gets asserted instead is described in §3.

## 2. Architectural principle this framework protects

The pipeline stays: `natural-language request → structured intent extraction (AI) → deterministic eligibility/scoring (recommendations.scoring) → ranked destinations → AI explanation`. The LLM must never silently become the ranking engine. Every scenario result separates *which layer* produced a given fact:

- Layer 1 — **intent extraction accuracy** (`evaluations.intent_eval`): did `ai.orchestration`'s real extraction call produce the fields this message actually implies?
- Layer 2 — **deterministic scoring/ranking correctness** (`evaluations.invariants`, `evaluations.trace`): given a structured request, does `recommendations.scoring.generate_recommendations` obey its own hard constraints, and is the additive score formula/ranking behaving as documented?
- Layer 3 — **explanation grounding** (`evaluations.grounding`): does the AI-generated reply stay faithful to the structured facts it was actually handed, never inventing a price, an availability claim, or a fabricated rating?

A bad recommendation gets diagnosed by *which* layer produced it, not guessed at — this is the whole reason the framework can run two different ways (see §4).

## 3. Scenario format

One scenario = one `evaluations.scenarios.Scenario` (a frozen dataclass), stored as one line of `evaluations/corpus/scenarios.jsonl`. Ground truth is split into layers matching §2:

- `expected_intent` — a **partial** dict of `ai.orchestration.INTENT_SCHEMA` fields. Only keys present get compared against what the real pipeline actually extracted; an omitted key means "not checked here," never "expected null." Lets a scenario focus on, say, budget-anchor accuracy without also having to pin down which month gets parsed.
- `deterministic_request` — a `recommendations.scoring.RecommendationRequest`-shaped dict. Used two ways: fed straight into `generate_recommendations` with **zero AI calls** (deterministic-only mode, §4), and as the "what extraction *should* have produced" reference for Layer 1. `None` for scenarios that never reach scoring at all (accommodation/visa/off-topic/feedback/...).
- `expected_flow` — which `stream_travel_recommendation` branch should fire (`recommendation`, `accommodation`, `accommodation_freeform`, `visa`, `booking`, `video`, `activity`, `off_topic`, `feedback`, `future_intent`, `recall`). Inferred from the real extracted intent's own boolean flags/`message_type` using the same branch-priority order `ai.orchestration` itself applies (`evaluations.runner._infer_expected_flow`) — a mismatch is classified as an `INTENT_EXTRACTION` failure, since routing to the wrong branch *is* an extraction problem by construction.
- `must_not_include_slugs` — destinations that would be **objectively wrong** if recommended (excluded by name, or logically incompatible with a stated hard constraint).
- `acceptable_slugs` — an optional whitelist the top recommendation should belong to. Left `None` for the large majority of scenarios (per §3's own don't-force-a-golden-answer principle) — only set where the constraint is narrow enough (e.g. `country="Japan"`) that the whole real candidate set is knowable in advance regardless of live climate.
- `expects_recommendations` / `expects_clarification` / `expects_zero_results` — which of three mutually-distinguished outcomes a scenario should produce: a real ranked list, an open-ended clarifying question (not enough signal was ever stated), or an honest zero-match result (enough signal was stated, but nothing in the real 384-destination catalog satisfies it). Conflating the second and third was a real design risk this schema deliberately guards against.
- `profile_overrides` — simulates an authenticated traveler's saved `TravelerProfile`/`Trip`/`TravelHistoryEntry` state (for `preference_fit`/`repetition_penalty` testing), via a throwaway synthetic user (`evaluations.profiles.synthetic_traveler`) created and deleted within the scenario run — never left behind in whatever database `evaluate_recommendations` is pointed at.
- `history` — prior conversation turns, passed as `history_override` to `stream_travel_recommendation`. **Known limitation**: this bypasses `ai.memory`'s Redis-backed conversation key entirely (`stream_travel_recommendation` forces `conv_key = None` whenever `history_override` is given), so `history`-based scenarios can test "is a prior turn's context actually read" but **cannot** exercise the cross-turn climate/budget accumulator (`ai.memory.get_climate_budget`/`update_climate_budget`) or the once-per-conversation profile-confirmation gate — see §14.

## 4. Two execution modes

- **Deterministic-only** (the default): builds a `RecommendationRequest` directly from `deterministic_request`, calls `recommendations.scoring.generate_recommendations` (optionally wrapped for a trace, §7). Zero AI calls, zero cost, exercises Layer 2 only. Every scenario supports this — one with no `deterministic_request` just gets an empty invariant set ("not applicable"), never skipped.
- **Full pipeline** (`--sample N` / `--full`): calls the real `ai.orchestration.stream_travel_recommendation()` entry point with a real `AIProvider`, so extraction, branching, scoring, and explanation all run exactly as they do for a live traveler. Costs real AI calls — see §8.

`ai.orchestration.stream_travel_recommendation` gained one additive, backward-compatible parameter for this: `intent_sink: dict | None = None`, populated with the final validated intent the call actually used. Without this, measuring extraction accuracy would have required a *second*, separately-issued extraction call — not only doubling cost, but risking measuring a different (LLM non-deterministic) intent than the one that actually produced the observed recommendations, silently invalidating the comparison. `recommendations.scoring.generate_recommendations` similarly gained an additive `trace: dict | None = None` parameter (§7). Neither changes behavior for any existing caller (default `None`, zero cost when omitted) — both are covered by the pre-existing test suites (600+ tests, unchanged pass rate) plus new evaluation-framework tests.

## 5. Deterministic invariants (`evaluations.invariants`)

Machine-verifiable properties that should **objectively never** be violated, independent of which destination "should" win:

- Excluded / objectively-wrong destinations never appear in the output.
- A stated hard budget ceiling / temperature bound / trip_type is never violated by anything in the result.
- Ranking is sorted by score, descending (and, checked separately for a sample, identical structured input produces an identical ranking — no hidden randomness).
- When a scenario declares `preferred_trip_types`/completed-trip history via `profile_overrides`, `preference_fit`/`repetition_penalty` are non-zero on the destinations they should affect — not silently zero as if the traveler were anonymous.
- **Structural, run-once invariant**: `check_no_affiliate_or_acquisition_signal_in_scoring` inspects `generate_recommendations`'s real signature and `RecommendationRequest`'s real fields for anything affiliate/click/acquisition-shaped, rather than trusting `recommendations/scoring.py`'s own boundary comment to stay true forever.

## 6. Metamorphic testing (`evaluations.metamorphic`)

Same traveler, exactly one axis varied. Only four axes have a **structural guarantee** given `recommendations/scoring.py`'s real filter chain, with everything else held equal — these get a real pass/fail check:

- Loosening `max_cost_of_living` (raising the ceiling) can only ever **grow** the DB-level-eligible set — `cost_of_living__lte` is a pure narrowing filter.
- Raising `min_temp_c` (or lowering `max_temp_c`) — a stricter climate bound — can only ever **shrink** the post-climate-filter eligible set.
- Narrowing `continent` → a specific `country` can only ever **shrink** the eligible set (country is a strictly more specific filter layered on top of continent's).
- Adding one more excluded slug removes **exactly** that slug and changes nothing else (`.exclude(slug__in=...)` runs before every other filter, independent of it).

A month-change pair has **no such guarantee** — real-world climate isn't monotonic across months, and inverts by hemisphere — so it gets no pass/fail check, only an informational observation (top winner, eligible-set Jaccard similarity) per the explicit instruction to report instability rather than encode an assumption the code doesn't actually back.

## 7. Recommendation trace (`evaluations.trace`)

Dev-only diagnostics: `python manage.py evaluate_recommendations --trace SCENARIO_ID` prints the "N eligible → rejections → scored → winner" shape for one scenario, using real numbers from that run — never exposed to a traveler. Built via `generate_recommendations`'s additive `trace` dict parameter (§4), not by reimplementing the filter chain a second time (which would risk drifting from the real logic).

## 8. Cost controls

Deterministic-only mode costs nothing and is the default — `python manage.py evaluate_recommendations` with no flags never calls OpenAI. Full-pipeline modes need an explicit `--sample N` or `--full`. `evaluations.cost.CostTracker` estimates spend from prompt/reply **character length**, not real token counts — neither `AIProvider.generate_structured_reply` (returns a plain dict) nor `.stream_reply` (raw text chunks) exposes usage data at any call site `ai.orchestration` actually uses, the same gap `analytics/instrumentation.py` already documents for production telemetry. The estimate is deliberately calibrated to the worst case (every full-pipeline scenario charged for 3 calls, the maximum a recommendation-flow scenario makes) so it over-, never under-, estimates. `--with-llm-judge` (§9) adds real cost only when passed.

## 9. Optional LLM-as-judge (`evaluations.llm_judge`)

Scores subjective qualities no structural check can reach — usefulness, clarity, whether the reply addresses the traveler's *actual* stated preferences, whether it communicates real trade-offs. Never the sole evaluation mechanism, never read by production ranking, and every judgment records its prompt version/model so results stay interpretable if the judge prompt later changes. Only runs with `--with-llm-judge`.

## 10. Explanation grounding (`evaluations.grounding`)

Structural, regex/substring checks — matching phrasing, not meaning — that a reply never claims something the application never actually gave it: a live price, checked availability, a consulted booking provider, or a fabricated rating/review count. Deliberately narrow: a fabrication phrased unusually enough to dodge every pattern here will slip through undetected (see §16).

## 11. Failure taxonomy (`evaluations.taxonomy`)

Every failed check maps to exactly one of `INTENT_EXTRACTION`, `HARD_CONSTRAINT`, `DESTINATION_DATA`, `SCORING`, `RANKING`, `EXPLANATION_GROUNDING`, `MISSING_INFORMATION`, `ROBUSTNESS`, `UNKNOWN` via a static name→category table, not an AI judgment call — keeps the taxonomy itself reproducible run over run, and tells us where engineering effort would actually pay off.

## 12. Development vs. holdout split

Every scenario carries `split: "dev" | "holdout"` (150 scenarios total, 127 dev / 23 holdout at corpus v1). Developers iterate against `dev` (the default for `evaluate_recommendations`). `holdout` exists to catch overfitting **to the corpus itself**, not to production data — never tune scoring weights or prompt wording directly against an individual holdout scenario's outcome; use it only to check whether an improvement measured on `dev` actually generalizes. `--split all` runs both together for a full baseline pass.

## 13. Run persistence and comparison

`evaluate_recommendations` writes one artifact directory per run under `evaluations/runs/<timestamp>_<label>/`: `meta.json` (corpus version, git SHA, timestamp, pass/fail counts, cost estimate, failure-taxonomy counts), `results.jsonl` (one full `ScenarioResult` per line), `metamorphic.jsonl`, and `summary.md` (human-readable). Deliberately files, not a database table — synthetic evaluation runs never belong in production analytics tables (`analytics.Event`/the warehouse), and Postgres buys nothing here a versioned, diffable file doesn't already give for free. `evaluations/runs/` is gitignored by default; a baseline run worth keeping as a permanent reference gets committed explicitly (`git add -f`), same as any other deliberately-kept artifact.

`python manage.py compare_evaluations <baseline> <candidate>` diffs two run directories: newly fixed scenarios, newly broken scenarios (regressions — surfaced first), unchanged failures, pass-rate deltas, and any scenario ids that only exist in one run (corpus changed between runs). A change that fixes 8 scenarios but breaks 20 is impossible to miss in this output.

## 14. Known limitations — what this framework still cannot reliably measure

Documented explicitly rather than left implicit, per the framework's own "don't overstate what was checked" principle:

- **The Redis-backed cross-turn climate/budget accumulator** (`ai.memory.get_climate_budget`/`update_climate_budget`) is not exercised by any `history`-based scenario — `history_override` forces `conv_key = None`, bypassing it entirely (§3). Testing the accumulator itself would need a real, sequential, same-`session_key` multi-call flow, which the current single-message `Scenario` shape doesn't represent. Not built this pass; a real gap, not an oversight.
- **The once-per-conversation profile-confirmation gate** (`ai.memory.is_profile_confirmed`) has the same `conv_key`-dependency issue.
- **Prose-level factual contradiction** (e.g. a reply calling a cost-tier-5 destination "budget-friendly") isn't reliably caught — `evaluations.grounding`'s checks are regex/substring pattern matches on specific fabrication phrasings, not semantic fact-checking against the destination's real fields.
- **No real token/cost data** — `evaluations.cost` estimates from character length only, since neither AI call site used by `ai.orchestration` exposes real usage (§8).
- **Live climate dependency** — deterministic-only scenarios asserting a hard temperature bound call the real, live `integrations.climate` provider (cached, but not frozen/replayed) by default; a scenario's exact eligible set can shift slightly if Open-Meteo's underlying historical data changes between runs. Hard-constraint invariants are unaffected (they check whatever the real climate said, not a predicted value) — only `acceptable_slugs`-style predictions would be sensitive to this, which is exactly why those are used sparingly (§3) and never for climate-dependent scenarios.
- **The LLM-as-judge is itself an LLM** — its subjective scores are evidence, not ground truth, and are reported separately from deterministic metrics for exactly this reason (§9).

## 15. Relationship to real-user analytics

Wanderes already has first-party analytics (`analytics.Event`, the warehouse views, `fact_recommendations`/`fact_acquisition_funnel`) covering real recommendation exposures and accommodation-click outcomes. Kept conceptually and physically separate from this framework:

- **Synthetic evaluation** answers "does the system behave according to our intended logic?" — reproducible, version-controlled, cheap to re-run.
- **Real-user analytics** answers "do travelers find recommendations useful enough to act?" — messy, real, can't be re-run.

An accommodation click is never automatically treated as proof a recommendation was *correct* — `analytics/queries.py`'s own module docstring already states this, and this framework doesn't change it. A high-click destination may simply be popular, familiar, cheaper, or shown more often; real-user behavior is evidence for *investigation*, never an automatic ranking-weight input. `recommendations/scoring.py`'s ranking-independence boundary (no affiliate/click/acquisition data reaches scoring — §5's structural invariant) is unaffected by anything in this framework.

**Explicit feedback status** (checked during this pass, not assumed): Wanderes already has `trips.Feedback` (rating/tags/comment on a destination or trip), feeding `trips.tasks.update_traveler_preferences_from_feedback` — but that's *preference learning* (rewrites a traveler's own future profile), not *quality measurement* of past recommendations; nothing in `recommendations/scoring.py` or `analytics/` currently uses `Feedback` to score recommendation quality. A `Helpful`/`Not helpful` or `This fits me`/`Not for me` signal, specifically for judging recommendation quality (not just general destination sentiment), doesn't exist yet — this framework's `evaluations.scenarios.Scenario` schema was kept deliberately generic enough (plain dataclass, JSONL storage) that such a signal, once it exists, could be folded into a future analysis pass without a schema rewrite. No feedback UI was added this pass — out of scope, and not "trivial and clearly consistent with existing UX" per the spec's own bar for that.

## 16. Why affiliate/click performance is not, and will not become, a ranking signal

Restated here (not just in `recommendations/scoring.py`'s own comment) because it's directly relevant to how this framework's evidence should and shouldn't be used: `evaluations.queries`-derived analytics answer *which channel or destination gets engagement*, never *which destination is objectively the best fit*. Wiring click/affiliate performance into `preference_fit`/`budget_fit`/etc. would let popularity or commission economics silently override genuine traveler fit — a monetization-philosophy decision, not a technical one, and one this project has repeatedly declined to make unilaterally. §5's structural invariant exists specifically so this claim stays machine-checked, not just documented.

## 17. Adding a new regression scenario

A fixed failure should normally become a permanent scenario (the corpus's own guard against the same bug recurring silently):

1. Add one `s(...)` call to `evaluations/corpus/build_corpus.py`, in the category section it best fits (see the file's own section headers). Reference only real catalog facts (slug/name/country/trip_type/cost_of_living) — `evaluations/tests/test_corpus.py` fails CI if a referenced slug doesn't exist in `travel/data/curated_destinations.json`.
2. Run `py evaluations/corpus/build_corpus.py` to regenerate `scenarios.jsonl` (deterministic, no randomness — the diff should only ever add/change the scenario(s) actually touched).
3. Run `python manage.py evaluate_recommendations --deterministic-only` (or `--sample` including the new scenario's split) to confirm it behaves as expected before committing.

## 18. Baseline procedure

The very first full run establishes the baseline — nothing gets tuned before it exists. Procedure: `python manage.py evaluate_recommendations --split all --full` against the current, unmodified implementation, saved with a durable label (e.g. `--label baseline`), the resulting `evaluations/runs/<...>_baseline/` directory committed with `git add -f`. Every later change is compared against this baseline via `compare_evaluations`, never against a hand-remembered impression of "how it used to behave."

## 19. Commands reference

```bash
# Deterministic-only, dev split (default, zero cost)
python manage.py evaluate_recommendations

# Full pipeline, real AI, a small sample of the dev split
python manage.py evaluate_recommendations --sample 20

# Full pipeline, whole corpus (both splits), the real baseline run
python manage.py evaluate_recommendations --split all --full --label baseline

# Add the optional subjective LLM-judge pass
python manage.py evaluate_recommendations --sample 20 --with-llm-judge

# Inspect one scenario's scoring trace (dev-only diagnostics)
python manage.py evaluate_recommendations --trace STR-005

# Compare two saved runs
python manage.py compare_evaluations 20260925-120000_baseline 20260926-090000_run
```
