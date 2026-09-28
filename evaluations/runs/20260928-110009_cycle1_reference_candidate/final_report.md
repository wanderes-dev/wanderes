# Wanderes Evaluation — Cycle 1.6: Fixture-Targeting Fix & Clean Reference Candidate

Scope: evaluation infrastructure only. No recommendation behavior, scoring, prompts, ranking, or destination data were changed. `ADV-001` and `STR-006` were deliberately left unfixed. This run is not promoted to the official baseline; Cycle 2 was not started.

## 1. Root cause investigation — why 4 scenarios were `DEPENDENCY_FAILURE` despite "full" fixture coverage

`refresh_weather_fixtures`'s `compute_needed_keys` mirrored each scenario's static `deterministic_request` through the same DB-level filter chain `generate_recommendations` uses, then captured weather only for the resulting candidate set. That's accurate for **deterministic-only** mode, but a **full-pipeline** run's real, live AI extraction doesn't always land on exactly the scenario's own asserted ground truth. Two distinct, concrete divergences were found:

- **No `deterministic_request` at all** (`MTT-007`, `ROB-015`): these are multi-turn/context-only scenarios whose real request only exists via conversation history. `compute_needed_keys` skipped them outright (`if deterministic_request is None: continue`), even though they do reach real scoring in a full-pipeline run.
- **A `deterministic_request` exists, but live extraction resolves a soft field differently**: `MET-003b`'s "mid-range budget" was captured for a strict `max_cost_of_living=3`, but live extraction can land on an adjacent tier, reaching a destination (Banff, 51.18/-115.57) never in the pre-computed set. `MTT-010`'s `trip_type="city"` filter excluded a real Japanese destination (35.01/135.77) that live extraction still legitimately reached.

## 2. The fix — generic, not scenario-specific

`evaluations/management/commands/refresh_weather_fixtures.py`:

- **`_effective_base_request(scenario)`** — falls back to a request synthesized from `expected_intent`'s populated fields when `deterministic_request` is `None`, instead of skipping the scenario. Still returns `None` (skip) for a scenario whose `expected_flow` isn't `"recommendation"` — nothing to capture for a visa/booking/accommodation/off-topic scenario regardless.
- **`_relaxed_requests(base_request)`** — adds a second candidate pass with `trip_type`/`max_cost_of_living` dropped, since those two fields are exactly what this codebase has repeatedly seen live extraction land off by one tier or category on. `continent`/`country` are deliberately **not** relaxed — they're a more binary match, already hardened by Cycle 1's geography-alias work, and relaxing them would multiply the needed-key count for little real benefit.
- **`_months_to_check(request)`** — when a scenario's effective month is genuinely unasserted (no `deterministic_request`, no `month` in `expected_intent`), captures all 12 months for that scenario's candidate set rather than guessing one.

No scenario ID, coordinate, or individual weather key is referenced anywhere in the fix itself — the mechanism is driven entirely by each scenario's own `expected_flow`/`expected_intent`/`deterministic_request` shape.

**Fail-closed behavior is untouched.** This fix only changes what `refresh_weather_fixtures` pre-computes as "needed" for *capture-time* population — `FixtureWeatherProvider.get_monthly_climate`, `MissingWeatherFixtureError`, and the `__bool__`-always-`True` fix from Cycle 1.5 were not touched at all. A key genuinely missing from the fixture still raises and is still tagged `DEPENDENCY_FAILURE`, exactly as before.

## 3. Regression tests

`evaluations/tests/test_refresh_weather_fixtures.py` (new, 14 tests) — no such test file existed before this cycle, which is likely why this class of gap went undetected. Covers: `_effective_base_request` using the real `deterministic_request` verbatim / returning `None` for a non-scoring flow / synthesizing from `expected_intent` / resolving `excluded_place_names` to real slugs; `_relaxed_requests`' no-op and relaxing cases; `_months_to_check`'s single-month and all-12-months cases; `compute_needed_keys` end-to-end for a destination only reachable via relaxation, for country staying a hard filter even when relaxed, for a `deterministic_request`-less scenario now getting covered, for an unasserted month covering every month, and for a non-scoring scenario contributing zero keys (cost-safety guard). A dedicated `RealCorpusRegressionTests` class (loads the real 384-destination catalog via `load_destinations`) asserts the exact four previously-missing keys are now targeted by the real corpus — ties the fix directly to the real, originally-reported failure, not just a synthetic shape.

## 4. Refresh — only genuinely missing entries captured

`refresh_weather_fixtures --dry-run` after the fix: **4608 needed, 3126 already captured, 1482 missing.** Ran for real against live Open-Meteo: **1482/1482 captured, 0 failures.** Post-capture dry-run: **4608/4608, 0 missing.** No existing entry was re-fetched or overwritten; nothing fabricated.

## 5. Deterministic reproducibility — re-verified after the fix

Two full-corpus deterministic-only runs (`det_1_6_run1`, `det_1_6_run2`) against the now-larger fixture: both 150/150 evaluable, 150/150 passed. Programmatically diffed `passed`/`scored_slugs`/`is_infrastructure_failure`/`failed_checks`/`flow_matched`/`invariants` for all 150 scenarios: **byte-for-byte identical.**

## 6. The official `cycle1_reference_candidate` run

`evaluate_recommendations --split all --full --label cycle1_reference_candidate` → `evaluations/runs/20260928-110009_cycle1_reference_candidate/`.

- **150 scenarios total, 150 evaluable, 0 infrastructure failures.** The cycle's stated goal (150/150 evaluable, 0 `DEPENDENCY_FAILURE`) is met.
- **138/150 passed — 92.0%.**
- **Dev: 117/127 (92.1%). Holdout: 21/23 (91.3%).**
- Cost: **$0.0568** (150 full-pipeline scenarios, character-length estimate, same documented limitation as always).
- Failure taxonomy: `INTENT_EXTRACTION: 12`, `SCORING: 2`. **`HARD_CONSTRAINT: 0`, `EXPLANATION_GROUNDING: 0`, `DEPENDENCY_FAILURE: 0`.**

## 7. Status of the eight specifically-tracked scenarios

| Scenario | Status | Detail |
|---|---|---|
| `ADV-001` | **Still fails** (deliberately left unfixed) | Consistent, reproducible (previously confirmed 5/5): "a beach below zero" scores real mild-climate beaches instead of zero results. |
| `STR-006` | **Still fails** (deliberately left unfixed) | Consistent, reproducible (previously confirmed 5/5): "hospedagem barata" routes to the accommodation flow, not the recommendation flow the corpus expects - a possible corpus-labeling question, not obviously a bug. |
| `CON-004` | **Still fails** | Same known, pre-existing, non-regression classification ambiguity ("exclude all of Europe but visit Paris") documented since Cycle 1. |
| `AMB-012` | **Now passes** | Confirmed ordinary ambiguous-category LLM variance (previously measured 3/5 pass over 5 reruns) - this run happened to land on a pass. |
| `ROB-002` | **Now passes** | Confirmed one-off sampling blip in the prior run, not a reintroduced freeform-accommodation bug (6/6 clean on immediate rerun, previously reported). |
| `ROB-017` | **Now passes** | Same as `ROB-002` - confirmed non-regression. |
| `STR-049` | **Now passes** | Confirmed ordinary variance (previously measured 4/5 pass). |
| `MTT-010` | **Newly evaluable, and fails - genuinely, reproducibly (5/5 reruns).** | The message ("cidade no japao, outubro, ja fui a toquio e osaka, quero outra") explicitly states both "cidade" (city) and "no japao" (in Japan), yet real extraction consistently returned `trip_type=null` and `country=null` (only `month` and the two excluded names matched). **Not a new regression** - `compare_evaluations` against `cycle1` (the original 2026-09-25 run, made with live weather, no fixture gap) shows `MTT-010` already failing there too. It was simply never checkable in `cycle1_verified`/`cycle1_verified_full` because of the exact fixture-targeting gap this cycle fixed. Reported here, not fixed - out of scope for an evaluation-infrastructure cycle, and a real candidate for Cycle 2's intent-extraction backlog. |

## 8. LLM instability vs. genuine failures - full accounting

- **Confirmed ordinary LLM variance** (not regressions): `AMB-012`, `ROB-002`, `ROB-017`, `STR-049` (all now passing, consistent with prior repeated-sampling evidence) and `STR-030` (newly failing here; 5 reruns show 4/5 pass - the same coin-flip pattern, not a new deterministic bug).
- **Genuinely reproducible, deliberately unfixed**: `ADV-001`, `STR-006` (both 5/5 reproducible in earlier investigation, unchanged this cycle since no recommendation-behavior code was touched).
- **Genuinely reproducible, newly measurable**: `MTT-010` (5/5 reproducible this cycle; pre-existing since `cycle1`, not new).
- **Known, accepted, non-regression ambiguity**: `CON-004` (self-contradictory message, documented since `cycle1`).
- **Remaining, not individually re-verified this cycle** (present in both runs, unchanged position): `ADV-008`, `CON-002`, `INC-010`, `MTT-006`, `MTT-008`, `STR-027`, `STR-037` - all `flow_mismatch` or `intent_field` misses in ambiguous/incomplete/conflicting/multi-turn categories, consistent with the same class of LLM classification variance already characterized in `cycle1_verified_full`'s own report.

## 9. Comparisons

**vs. baseline (`20260925-114531_baseline`)**: 75.3% → 92.0%. 26 newly fixed, **1 newly broken (`CON-004`** — known non-regression), 11 still failing in both, 112 still passing in both, **0 infrastructure-affected** (baseline predates the fixture system entirely, so nothing to exclude on that basis).

**vs. Cycle 1 (`20260925-142147_cycle1`)**: 86.0% → 92.0%. 10 newly fixed (8 of the original nine, plus `STR-012`/`MET-006b`), **1 newly broken (`STR-030`** — confirmed variance), 11 still failing in both (includes `MTT-010` - confirming it already failed back in Cycle 1, not a new issue), 0 infrastructure-affected.

**vs. `cycle1_verified_full` (`20260928-090035_cycle1_verified_full`)**: 90.4% → 92.0%. 4 newly fixed (`AMB-012`, `ROB-002`, `ROB-017`, `STR-049` — all confirmed variance), **1 newly broken (`STR-030`** — confirmed variance), 10 still failing in both, 131 still passing in both, 4 infrastructure-affected (`MET-003b`, `MTT-007`, `MTT-010`, `ROB-015` - the four scenarios this cycle's fix specifically targeted; correctly excluded from fixed/broken since they weren't evaluable in the prior run).

No regression is hidden behind the improved aggregate: both "newly broken" items across all three comparisons (`CON-004`, `STR-030`) were individually investigated and confirmed non-regressions (§8).

## 10. Metamorphic and geo/exclusion targets - unaffected, reconfirmed

Same 9/9 structural metamorphic checks pass as in `cycle1_verified_full` (this cycle touched no scoring/matching code, so no change expected or found). `MET-003b`, `MTT-007`, `ROB-015` - three of the four previously-infrastructure-affected scenarios - are now evaluable and passing, closing out the last visibility gap on Cycle 1's geo-normalization and prior-visit-exclusion targets. `MTT-010` (the fourth) is now evaluable too, and genuinely fails (§7) - a real, pre-existing gap, not touched by anything in Cycle 1.6.

## 11. Verification performed

- Fixture dry-run before/after: 3126/4608 → 4608/4608, 0 missing.
- Live capture: 1482/1482, 0 failures.
- Deterministic reproducibility: two full-corpus runs, diffed programmatically, byte-identical.
- Full-pipeline evaluation: 150/150 evaluable, 0 infrastructure failures - the cycle's explicit goal met.
- `compare_evaluations` against all three required historical runs.
- Targeted reruns (5 samples each) of every newly-changed-status scenario (`MTT-010`, `STR-030`) to separate variance from regression, mirroring Cycle 1.5's own methodology.
- Full Django test suite: **810/810 passing** (14 new), zero regressions.
- `ruff check .`: **clean**.
- No production recommendation-behavior file was modified - only `evaluations/management/commands/refresh_weather_fixtures.py` (evaluation-infrastructure code), its new test file, and the fixture data file itself changed.

## 12. Files changed this cycle (uncommitted - awaiting instruction)

- `evaluations/management/commands/refresh_weather_fixtures.py` - the generic targeting fix.
- `evaluations/tests/test_refresh_weather_fixtures.py` - 14 new regression tests (new file).
- `evaluations/fixtures/weather.json` - 1482 additional real captured entries.

(The prior 3126-entry fixture population was already committed separately, per explicit instruction, before this cycle began.)

## 13. Evaluation cost

**$0.0568** for this run's 150 full-pipeline scenarios. The `MTT-010`/`STR-030` repeated-sampling investigation (§8) added roughly 10 more scenario-level full-pipeline calls at the same rate, run as ad hoc diagnostics rather than persisted evaluation runs.

## 14. Recommendation on baseline promotion

Not promoted here, per this cycle's explicit scope. On the evidence: this run has **zero infrastructure failures for the first time in this framework's history**, every "newly broken" scenario across all three comparisons is individually confirmed as non-regression LLM variance, and the two deliberately-unfixed known issues (`ADV-001`, `STR-006`) plus the one newly-measurable real gap (`MTT-010`) are all clearly identified with root causes, not mysteries. This looks like the strongest baseline candidate produced so far - but promoting it, deciding whether to commit this cycle's code changes, and deciding what (if anything) to do about `MTT-010`/`ADV-001`/`STR-006`/`CON-004` are left to the user, per this cycle's explicit instruction not to promote and not to start Cycle 2.
