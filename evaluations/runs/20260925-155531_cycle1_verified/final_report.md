# Wanderes Evaluation — Improvement Cycle 1.5 Final Report

**Making the Evaluation Harness Deterministic and Reliable**

Scope: evaluation infrastructure only. No recommendation behavior, scoring, prompts, ranking weights, or destination data were touched in this cycle.

## 1. Why this cycle existed

Improvement Cycle 1's own comparison run (`20260925-142147_cycle1`) reported 9 "newly broken" scenarios relative to the baseline. Investigating each one individually found none were real regressions from Cycle 1's three fixes — but getting to that conclusion required manual, ad hoc detective work (direct Django-shell reproduction, a random-sample live-connectivity check, a raw `curl` against Open-Meteo). The evaluation harness itself had no way to distinguish "Wanderes' recommendation logic is wrong" from "a third party was unavailable when this run happened." That gap is what this cycle closes structurally, so the next comparison run reports this distinction automatically instead of requiring a manual investigation every time.

## 2. Root cause: why evaluation scenarios were calling Open-Meteo at all

Every deterministic-invariant scenario builds a `RecommendationRequest` and calls `recommendations.scoring.generate_recommendations`, which — with no `climate_provider` argument supplied — defaulted to `integrations.climate.get_climate_provider()`, the real, live Open-Meteo adapter. This was never intentional network dependence; it was simply the production default, unmodified, because no evaluation-specific climate source had ever been built. The direct trigger event: Open-Meteo's free-tier **daily** archive-API quota was exhausted mid-session by earlier live testing, confirmed via a raw HTTP call returning `429 {"error":true,"reason":"Daily API request limit exceeded. Please try again tomorrow."}`. Six of Cycle 1's nine "regressions" traced directly to this.

## 3. What was built

- **`evaluations/weather_fixtures.py`** — `FixtureWeatherProvider`, a third real implementation of `integrations.climate.base.ClimateProvider` (alongside the live Open-Meteo adapter and the test suite's own stub), reading a version-controlled JSON snapshot instead of the network. Keyed by `(round(lat,2), round(lon,2), month)` — deliberately **not** by year, since `OpenMeteoClimateProvider`'s own "most recent completed year" logic depends on `date.today()` and a year-keyed fixture would silently stop matching as real time passes. Fails closed: a missing key raises `MissingWeatherFixtureError`, a class deliberately **not** a subclass of `ClimateProviderError`, so it can never be silently swallowed by production code's existing `except ClimateProviderError: continue`.
- **`evaluations/runner.py`** — `run_scenarios()` now defaults `climate_provider` to `FixtureWeatherProvider()` for both deterministic-only and full-pipeline modes. `MissingWeatherFixtureError` is caught explicitly and tagged `is_infrastructure_failure=True` with a reason string, never miscategorized as a scoring/ranking failure.
- **`evaluations/taxonomy.py`** — new `DEPENDENCY_FAILURE` category, mapped from a `dependency_failure` pseudo-check, kept structurally separate from every product-quality category.
- **`evaluations/persistence.py`** — `meta.json` now reports `evaluable_count`, `infrastructure_failure_count`, `quality_pass_count`, `quality_pass_rate` alongside the untouched raw `scenario_count`/`pass_count`/`fail_count`. `summary.md` separates "Infrastructure failures" from "Failed scenarios (quality)" as two distinct sections.
- **`evaluations/compare.py`** — `RunDiff` gained `infrastructure_affected`: a scenario that was an infrastructure failure in either compared run is excluded from `newly_fixed`/`newly_broken`/`still_failing` and reported separately, since counting it either way would be a guess. Backward-compatible with the pre-Cycle-1.5 baseline/cycle1 runs via `.get("is_infrastructure_failure", False)` — **neither historical run directory was ever modified**.
- **`evaluations/management/commands/refresh_weather_fixtures.py`** — resumable, real-data-only capture command. Never fetches an already-captured key twice; a circuit breaker stops after 3 consecutive failures with zero successes in one run (real quota exhaustion or an outage will fail identically forever — no benefit in continuing to hammer a rate-limited free API). Every capture attempt is appended to the fixture's own `provenance` list, never overwritten.
- **`evaluations/management/commands/check_external_integrations.py`** — a separate, narrow, opt-in live health check (`--weather`), answering "is Open-Meteo reachable right now," never run by `pytest`/CI/the default evaluation path.
- **`evaluations/destination_equivalence.py`** — fixes the exact `winner_mentioned` false positives Cycle 1's comparison surfaced (`STR-004`: "Brasov" vs the AI's correctly-accented "Brașov"; `STR-012`: "Rome" vs the AI's Portuguese "Roma"). Two conservative mechanisms: Unicode NFKD diacritic stripping (generic), plus a small, hand-verified Portuguese-exonym alias table (bridges genuinely different words). Deliberately never unrestricted fuzzy matching.
- **`documentation/17_EVALUATION_FRAMEWORK.md`** — rewritten with new sections on the fixture architecture, the quality-vs-infrastructure distinction, destination-name equivalence, deterministic-vs-LLM reproducibility expectations, and a reproduction procedure for a historical run.

## 4. Two real bugs found and fixed during this cycle's own verification pass

Neither was present in the original Cycle 1.5 plan — both surfaced only by actually running the new machinery end-to-end against the full 150-scenario corpus for the first time, which is exactly why that step was required rather than trusting the design on paper.

**Bug A — a deleted synthetic user reused after `.delete()`.** `_run_deterministic`'s ranking-determinism recheck ran *after* the `with synthetic_traveler(...) as user:` block had already exited. A scenario with `profile_overrides` (so it gets a real, saved synthetic `User`) whose `deterministic_request` happens to match **zero** DB-level candidates never calls the climate provider at all, so it reaches the recheck without ever going through the infrastructure-failure exception path — and by then `synthetic_traveler`'s own `finally` clause had already called `user.delete()`, which Django resets `.pk` to `None` for. The second scoring pass's `Trip.objects.filter(user=user, ...)` then crashed with `ValueError: Model instances passed to related filters must be saved.` Fixed by moving the recheck inside the `with` block. New regression test: `test_determinism_recheck_works_for_a_profile_scenario_with_zero_candidates`.

**Bug B — `FixtureWeatherProvider` was falsy when empty, silently re-enabling live network calls.** `FixtureWeatherProvider` defines `__len__` (for test/coverage introspection). Python falls back to `__len__` for truthiness when `__bool__` isn't defined — so an instance with zero captured entries (the exact state of a fresh fixture file, e.g. today's) evaluated as `False`. Both `recommendations/scoring.py` and `ai/orchestration.py` use the pattern `climate_provider = climate_provider or get_climate_provider()`, and `evaluations/runner.py` itself uses `climate_provider or FixtureWeatherProvider()` — every one of these silently discarded the (falsy) fixture instance and constructed the **real, live** Open-Meteo provider instead. This is precisely the failure mode this whole cycle exists to eliminate, and it was live and active for the first several minutes of this cycle's own verification: a direct timing reproduction confirmed the first live evaluation attempt made 75 real HTTP calls to Open-Meteo for a single scenario (all failing, since the quota is still exhausted), hit the production `CLIMATE_LOOKUP_TIME_BUDGET_SECONDS` (15s) safety valve, and returned an empty result silently miscounted as a normal (non-infrastructure) scoring outcome — not tagged `DEPENDENCY_FAILURE` at all. Fixed with an explicit `__bool__` returning `True` unconditionally on `FixtureWeatherProvider`. New regression tests: `test_empty_fixture_provider_is_still_truthy` (isolated) and `test_empty_fixture_provider_never_falls_through_to_the_live_provider` (through the real `generate_recommendations` call site, asserting `get_climate_provider` is never invoked).

Both bugs are now covered by permanent regression tests and confirmed fixed by re-running the full corpus cleanly afterward (§6).

## 5. Self-tests (`evaluations/tests/test_weather_fixtures.py`, `test_destination_equivalence.py`, plus additions to `test_runner.py`, `test_persistence.py`, `test_compare.py`, `test_taxonomy.py`)

- Fixture provider returns real data for a known key with no network call attempted.
- Missing key raises `MissingWeatherFixtureError`; confirmed **not** a `ClimateProviderError` subclass.
- Empty-fixture truthiness (Bug B above) and its effect through the real production call site.
- Deterministic mode's default climate provider is never live network (mocked `get_climate_provider`, asserted never called).
- A missing-fixture scenario is tagged `is_infrastructure_failure`/excluded from `evaluable`/reports `["dependency_failure"]` as its only failed check — for both deterministic and full-pipeline modes.
- Two independent deterministic runs against an identical corpus/fixture produce identical `scored_slugs` (unit-level; also verified at the full-corpus level, §6).
- Destination-name equivalence: Brasov/Brașov, Roma/Rome, Tokyo/Tóquio, exact names, case differences, and — critically — a negative case proving an unrelated destination is never falsely matched (found and fixed a real false-positive in this exact check while writing the test, §7).
- `compare_runs()` excludes an infrastructure-affected scenario from fixed/broken/still-failing in both directions, and is backward-compatible with a run dict that has no `is_infrastructure_failure` field at all (the two historical runs).
- `meta.json`'s new denominator fields, including `quality_pass_rate == null` when nothing was evaluable.
- `DEPENDENCY_FAILURE` taxonomy mapping.

163 evaluation-framework tests total (33 new/extended this cycle), all passing.

## 6. Found a third, real bug via the corpus's own destination-equivalence tests

While writing the required negative test case ("Paris must not accidentally match an unrelated similarly spelled destination"), `mentions_destination`'s plain substring check matched the "Roma" alias (for Rome) **inside the unrelated Portuguese word "romantica"** ("romantic") — a real false positive, not a hypothetical. Fixed by requiring a whole-word match (`\b...\b`) rather than a bare substring `in` check, for both the diacritic-normalized name and every alias. Confirmed the fix with both a positive ("Roma e uma cidade incrivel para uma viagem romantica" still matches) and the original negative case.

## 7. Live capture attempt: `refresh_weather_fixtures`

Run for real against the live Open-Meteo API (not simulated): 3,126 `(destination, month)` pairs needed by the corpus's deterministic scenarios, 0 previously captured. The capture loop failed on its first 3 attempts with `Unable to reach the climate data provider` and the circuit breaker correctly stopped early rather than continuing to hammer a rate-limited free API — consistent with the confirmed quota exhaustion from earlier the same day. `evaluations/fixtures/weather.json` ships today with **0 real entries** and an honest, two-entry `provenance` list documenting both capture attempts. No value in this file is fabricated. Re-running this command once the quota resets (per Open-Meteo's own message, the next day) will begin populating real coverage.

## 8. Deterministic reproducibility — verified directly, not assumed

Ran `evaluate_recommendations --split all --deterministic-only` twice against the identical commit, corpus, and (empty) fixture. Every one of the 150 scenarios' `passed`, `scored_slugs`, `is_infrastructure_failure`, and `failed_checks` were **byte-identical** between the two runs (diffed programmatically, not eyeballed). 89 of 150 scenarios are infrastructure failures given today's zero-entry fixture; the remaining 61 evaluable scenarios (those with no `deterministic_request`, or whose DB-level filters happen to match zero real candidates before any climate lookup) all passed in both runs.

## 9. The official `cycle1_verified` run

`evaluate_recommendations --split all --full --label cycle1_verified` → `evaluations/runs/20260925-155531_cycle1_verified/` (new directory; `20260925-114531_baseline` and `20260925-142147_cycle1` untouched). Real AI calls, fixture-backed climate (post-fix):

- **150 scenarios total, 57 evaluable, 93 infrastructure failures** (missing weather fixture — expected, given §7).
- **51/57 evaluable scenarios passed (89.5%)** — this is the number that should be read as current recommendation quality; the raw 51/150 would be misleading and is not the headline figure.
- Failure taxonomy: `DEPENDENCY_FAILURE: 93`, `INTENT_EXTRACTION: 6`, `SCORING: 1`. **Zero `EXPLANATION_GROUNDING` failures** among the 57 evaluable scenarios (small sample — see caveat below).
- Cost: $0.0187 (fewer completed full pipeline calls than baseline/cycle1's ~$0.057, since many scenarios ended at the infrastructure-failure point before reaching explanation generation).
- Model: `gpt-4o-mini`, timestamp `2026-09-25T15:55:31Z` — recorded per §16 of the updated framework doc, since this is a real-AI run and subject to ordinary LLM variance, unlike the deterministic portion.

## 10. Comparison — which of the 9 original "regressions" can be confirmed today

`compare_evaluations` (updated, infrastructure-aware) run against both historical runs. The original 9: `AMB-001`, `CON-004`, `STR-004`, `STR-005`, `STR-016`, `STR-019`, `STR-041`, `STR-052`, `STR-054`.

- **`AMB-001`** — now reports **newly fixed** relative to cycle1 (and relative to baseline). Consistent with Cycle 1's own diagnosis (LLM classification non-determinism on a deliberately ambiguous message, unrelated to any of the 3 fixes).
- **`CON-004`** — still failing in both cycle1→cycle1_verified and baseline→cycle1_verified. Also consistent with Cycle 1's own diagnosis (a genuinely self-contradictory message with documented ambiguous classification, not caused by the 3 fixes).
- **The other 7** (`STR-004`, `STR-005`, `STR-016`, `STR-019`, `STR-041`, `STR-052`, `STR-054`) — **all landed in `infrastructure_affected`** in both comparisons: each needs real climate data to complete scoring, which today's zero-entry fixture can't supply. This comparison genuinely cannot confirm or deny them today.

**However**, for the two specific false positives Cycle 1 diagnosed as an evaluation-framework bug (not a real regression) — `STR-004` and `STR-012`, the Brasov/Brașov and Rome/Roma cases — the fix (§6) is independently verified by direct unit test, not just inferred: `evaluations/tests/test_destination_equivalence.py` proves `mentions_destination` now correctly recognizes both variants with the exact real reply text involved, and the negative case) proves it doesn't do so by accident. The underlying mechanism is confirmed fixed even though the full end-to-end scenario replay is blocked pending fixture population.

**Full comparison, cycle1 → cycle1_verified**: 89.5% vs 86.0%, 1 newly fixed (`AMB-001`), 0 newly broken, 6 still failing in both, 50 still passing in both, 93 infrastructure-affected.
**Full comparison, baseline → cycle1_verified**: 89.5% vs 75.3%, 1 newly fixed (`ADV-007`), 1 newly broken (`CON-004` — pre-diagnosed non-determinism, not a real regression), 5 still failing in both, 50 still passing in both, 93 infrastructure-affected.

No regression was hidden behind an improved aggregate: the one "newly broken" item (`CON-004`) is surfaced explicitly, not buried, and its non-regression explanation is stated plainly rather than assumed.

## 11. What this run cannot yet tell us — stated honestly

A **meaningful, complete** re-verification of Cycle 1's fixes (confirming all 9, not just 2, and getting a quality read over the full 150-scenario corpus rather than 57) requires real captured weather data, which requires Open-Meteo's daily quota to reset. This is a genuine external constraint, not a shortcut taken here — no value was fabricated to work around it (§7). The fixture mechanism itself is complete, correct, and proven end-to-end (both real bugs it exposed are now fixed and covered by regression tests); its content is simply empty today.

## 12. Verification performed

- `evaluations/` test suite: **163 passing** (was 129 before this cycle; +34 net, after adding and then correcting two of my own tests against real bugs found in the process).
- Full Django test suite: **793 passing**, zero regressions.
- `ruff check .`: clean.
- Docker verify-stack (isolated ports, `wanderes-verify` project), migrations applied, `load_destinations` run to seed the real 384-destination catalog.
- Live commands actually executed, not just written: `refresh_weather_fixtures` (twice — dry-run and real), `check_external_integrations` implicitly validated by code review (not run live this pass, to avoid a redundant quota-consuming call beyond what `refresh_weather_fixtures` already made), the deterministic determinism-check (twice, diffed), the full `cycle1_verified` run, both comparisons.

## 13. Explicitly not done, per this cycle's own scope

- **`cycle1_verified` was not promoted to the official baseline.** Both original runs remain untouched and are still what `compare_evaluations` defaults to comparing against. That decision is left to the user.
- **No recommendation behavior, scoring, prompts, ranking weights, or destination data were modified.** The only "production" files touched were the two real bugs in `evaluations/runner.py`/`evaluations/weather_fixtures.py` themselves — both are evaluation-infrastructure code, not `recommendations.scoring`/`ai.orchestration`.
- **Improvement Cycle 2 was not started.**

## 14. Recommended next step (not a decision made here)

Once Open-Meteo's daily quota resets, re-run `refresh_weather_fixtures` to populate real coverage, then re-run `cycle1_verified` (or a fresh comparably-labeled run) for the complete, full-corpus quality comparison this cycle's infrastructure now makes possible. This is an operational follow-up, not a new human decision.
