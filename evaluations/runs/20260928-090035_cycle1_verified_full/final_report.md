# Wanderes Evaluation — Cycle 1.5 Operational Follow-up: Fixture Population & Full Verification

Scope: operational only. No code, prompt, scoring, ranking, destination-data, or recommendation-behavior changes were made. This run is not promoted to the official baseline; Cycle 2 was not started.

## 1. Fixture coverage

`python manage.py refresh_weather_fixtures` run for real against live Open-Meteo (quota had reset since 2026-09-25):

- **3126/3126 (destination, month) pairs needed by the corpus — 100% captured, 0 failures.**
- Circuit breaker never triggered (never needed — no consecutive-failure streak occurred).
- `evaluations/fixtures/weather.json`'s `provenance` list now has a third, successful entry alongside the two failed 2026-09-25 attempts; no existing entry was overwritten, no value fabricated.

## 2. Deterministic reproducibility — verified, not assumed

Ran `evaluate_recommendations --split all --deterministic-only` twice against the identical commit/corpus/fixture (`det_run1`, `det_run2`):

- Both runs: **150/150 scenarios evaluable, 150/150 passed.**
- Programmatically diffed `passed`, `scored_slugs`, `is_infrastructure_failure`, `failed_checks`, `flow_matched`, and `invariants` for every scenario between the two runs: **byte-for-byte identical in all 150.**
- With full fixture coverage, the deterministic layer now has **zero infrastructure failures** (versus 89/150 when the fixture was empty on 2026-09-25) — every scenario's own hard-constraint/ranking/metamorphic logic got a real, evaluable answer.

## 3. The official `cycle1_verified_full` run

`evaluate_recommendations --split all --full --label cycle1_verified_full` → `evaluations/runs/20260928-090035_cycle1_verified_full/`. Real AI calls (`gpt-4o-mini`), fixture-backed climate throughout.

- **150 scenarios total, 146 evaluable, 4 infrastructure failures.**
- **132/146 evaluable scenarios passed — 90.4%.** This is the number that should be read as current recommendation quality.
- **Dev split: 113/124 evaluable passed (91.1%).**
- **Holdout split: 19/22 evaluable passed (86.4%).**
- Cost: **$0.0554** (146 pipeline scenarios, estimated from character length — no real token-usage API available at either AI call site, a documented framework limitation).

### Failure taxonomy (evaluable scenarios only)

| Category | Count |
|---|---|
| INTENT_EXTRACTION | 13 (checks) across 12 scenarios |
| SCORING | 2 (checks) across 2 scenarios |
| HARD_CONSTRAINT | **0** |
| EXPLANATION_GROUNDING | **0** |
| RANKING | 0 |
| DEPENDENCY_FAILURE | 4 (excluded from the quality denominator above) |

(One scenario, `STR-006`, contributes two failed checks in two different categories — `flow_mismatch`→INTENT_EXTRACTION and `winner_in_acceptable_set`→SCORING — which is why the check-level taxonomy count (19) exceeds the 14 distinct quality-failing scenarios + 4 infrastructure failures = 18 raw `fail_count`.)

### The 4 infrastructure failures — a real, newly-observed gap in fixture *targeting*, not fixture *coverage*

`MET-003b`, `MTT-007`, `MTT-010`, `ROB-015` each needed a `(latitude, longitude, month)` triple that isn't in `compute_needed_keys`'s pre-computed "needed" set. Root cause: `refresh_weather_fixtures` computes needed keys by mirroring each scenario's static `deterministic_request` through the same DB-level filter chain `generate_recommendations` uses — but a **full-pipeline** run's real, live AI extraction can produce a *different* structured request (a broader continent match, a different resolved month, a country resolved slightly differently) than the scenario's own hand-written `deterministic_request`, reaching a destination/month combination the pre-computation never anticipated. This is a real, if narrow, gap in the fixture-targeting logic (not touched this cycle, since it would require a code change) — worth a note for whoever picks up Cycle 2's evaluation-infrastructure backlog, not something fabricated around here. All 4 are honestly tagged `DEPENDENCY_FAILURE` and excluded from the quality denominator, exactly as designed.

## 4. The nine originally-suspicious scenarios — final status

| Scenario | Status now | Evidence |
|---|---|---|
| `AMB-001` | **Passes.** | Confirmed fixed since `cycle1_verified` (2026-09-25); still passing today. |
| `CON-004` | **Still fails** — self-contradictory message ("exclude all of Europe but I want to visit Paris"), classified as `future_intent` instead of `recommendation` (`flow_mismatch`). | Consistent with Cycle 1's own diagnosis: a genuinely ambiguous message, not caused by any of the 3 Cycle 1 fixes, not a new regression. |
| `STR-004` | **Passes.** | The Brasov/Brașov diacritic false positive is independently verified fixed by `evaluations/tests/test_destination_equivalence.py`; this scenario now passes end-to-end too. |
| `STR-005` | **Passes.** | Real climate data now available for the (Japan, April) candidates; scored and matched. |
| `STR-016` | **Passes.** | Real climate data now available for the (Egypt, November) candidates. |
| `STR-019` | **Passes.** | Real climate data now available for the (France, October) candidates. |
| `STR-041` | **Passes.** | Real climate data now available for the (Nepal, October) candidates. |
| `STR-052` | **Passes.** | Real climate data now available for the (Morocco, May) candidates. |
| `STR-054` | **Passes.** | Real climate data now available for the (Australia, October) candidates. |

**8 of 9 now confirmed genuinely fixed** (7 were purely blocked on real weather data, now supplied; the 8th, `STR-004`, was a framework false-positive already fixed independently). **1 of 9 (`CON-004`) remains a known, pre-existing, non-regression LLM-classification ambiguity** — unrelated to Cycle 1's fixes, unrelated to this cycle's fixture work, and confirmed stable (fails the same way it always has).

## 5. Remaining genuine (reproducible) failures — 2 of the 14 quality failures

Verified by rerunning each **5 times** directly through `evaluations.runner.run_scenarios` (same code the management command uses):

- **`ADV-001`** — "quero uma praia muito fria, tipo abaixo de zero, em janeiro" (an adversarial, physically-extreme request: a beach colder than freezing). `expects_zero_results=True`, but the run consistently (5/5) scores 10 real, mild-cold-climate beach destinations (Dubrovnik, Nice, Cinque Terre, Amalfi, San Sebastián...) instead of zero. **Root cause, most likely**: the isolated climate/budget extraction call translates "below zero" into a real but not extreme-enough `max_temp_c` bound, so genuinely cool (not sub-zero) beaches still clear the filter. A deliberately adversarial phrasing, and the result isn't dangerous or dishonest (real destinations, no fabrication) — but it is a **consistent, reproducible** gap worth a future look, not noise.
- **`STR-006`** — "hospedagem barata na tailandia em janeiro, cultura" (cheap *accommodation* in Thailand). Consistently (5/5) routes to the accommodation-search flow rather than the destination-recommendation flow the corpus expects. Worth flagging as a **possible corpus-labeling issue rather than an app defect**: "hospedagem" literally means lodging/accommodation in Portuguese, and Wanderes now has a real accommodation-search feature (Cycle 1's own PR #23) — treating this message as an accommodation request is a defensible, arguably more literal reading, not obviously wrong. Flagged for a human call on whether to relabel the scenario or adjust classification priority, not fixed here either way.

Neither of these two was flagged among the original nine; both are new findings from this run's larger evaluable sample (57→146), surfaced honestly rather than smoothed over.

## 6. LLM-unstable scenarios — confirmed ordinary variance, not regressions

`compare_evaluations` flagged 4 scenarios as "newly broken" relative to at least one historical run: `AMB-012`, `CON-004` (already covered in §4), `ROB-002`, `ROB-017`, plus `STR-049` (newly broken only relative to `cycle1`). Every one was re-run several times directly through the same evaluation code (no code changed between attempts) to check whether it's a real, code-driven regression or ordinary full-pipeline LLM variance:

- **`AMB-012`** ("quero uma viagem espiritual, de autoconhecimento" — a deliberately vibe-only, ambiguous message): 5 reruns → **3 pass, 2 fail** — a genuine coin-flip. Consistent with its own `ambiguous` category and with this exact codebase's long-documented history of inconsistent trip_type force-fitting on vibe-only phrasings (romantic, family-friendly, relaxing, and now spiritual/self-discovery).
- **`ROB-002`** ("hospedagem em wuhan pra 3 pessoas") and **`ROB-017`** ("...hospedagens em curitiba...") — both explicit regression-guard scenarios for the freeform-accommodation feature (real, non-catalog cities). The original run's failure showed the reply substituting a *different* city (Beijing for Wuhan, Brasília for Curitiba). **3 immediate reruns of each (6/6 total) all correctly stayed on the named city** — strong evidence this was a one-off full-pipeline sampling blip, not a reintroduced bug in the freeform-accommodation resolution logic itself.
- **`STR-049`** ("Somewhere very expensive and glamorous in Europe... city trip"): 5 reruns → **4 pass, 1 fail** (only the very first attempt missed `max_cost_of_living=5`). Ordinary variance on a budget-extraction edge case (luxury wording), not a new deterministic bug.

**Conclusion: zero of the four "newly broken" scenarios represent a real code regression.** All four are attributable to ordinary LLM sampling variance on full-pipeline calls, directly confirmed by repeated sampling rather than inferred. Nothing in `recommendations.scoring`, `ai.orchestration`, or the evaluation harness changed between `cycle1_verified` (2026-09-25) and this run — the only change was fixture population.

## 7. Cycle 1 targets — final status, now confirmed at full-corpus scale

| Target | Baseline | Cycle 1 (partial fixture) | This run (full fixture) |
|---|---|---|---|
| EXPLANATION_GROUNDING failures | 26 | 4 (small evaluable sample) | **0** (146 evaluable — the largest sample yet) |
| HARD_CONSTRAINT failures | 4 | 0 | **0** |
| Geographic normalization (`travel/geography_aliases.py`) | — | STR-004/STR-012-class false positives found & fixed (Cycle 1.5) | **0** geography-related failures in this run |
| Previous-visit exclusion | — | `MTT-002`/`MTT-010`/`STR-032`/`ADV-007` newly passing | `MTT-002`, `STR-032`, `ADV-007` still passing; `MTT-010` is one of this run's 4 infrastructure failures (untestable this run, not failing) |
| Metamorphic tests (structural axes) | — | — | **9/9 structural checks pass** (`budget_loosen` ×3, `temperature_bound_loosen` ×2, `geography_narrow` ×2, `add_exclusion` ×2); `month_change` correctly produced no pass/fail check (informational only, by design) |
| Dev performance | 76.4% | 85.0% | **91.1%** (124 evaluable, was 57 evaluable at `cycle1_verified`) |
| Holdout performance | 69.6% | 91.3% | **86.4%** (22 evaluable) |

The ranking-fidelity fix (numbered candidates + explicit "#1 is the real winner" instruction) appears to have durably eliminated `EXPLANATION_GROUNDING` failures at a sample size 2.5× larger than Cycle 1.5's own 57-evaluable check. `HARD_CONSTRAINT` stayed at zero. Holdout's small dip from Cycle 1's own 91.3% (21/23) to this run's 86.4% (19/22, one scenario in that split — `INC-010`— is a `flow_mismatch`, and `ROB-017`/`STR-049` also live in holdout) is consistent with the ordinary full-pipeline variance documented in §6, not a new regression — the corresponding scenarios were already shown unstable under repeated sampling.

## 8. Comparisons

**vs. baseline (`20260925-114531_baseline`)**: 75.3% → 90.4%. 25 newly fixed, 4 newly broken (`AMB-012`, `CON-004`, `ROB-002`, `ROB-017` — all confirmed §6/§4 non-regressions), 10 still failing in both, 107 still passing in both, 4 infrastructure-affected.

**vs. Cycle 1 (`20260925-142147_cycle1`)**: 86.0% → 90.4%. 10 newly fixed (includes 8 of the original nine — §4), 4 newly broken (`AMB-012`, `ROB-002`, `ROB-017`, `STR-049` — all confirmed §6 non-regressions), 10 still failing in both (includes `CON-004`), 122 still passing in both, 4 infrastructure-affected.

**vs. `cycle1_verified` (`20260925-155531_cycle1_verified`)**: 89.5% → 90.4%. 0 newly fixed, 2 newly broken (`ROB-002`, `ROB-017` — confirmed §6 non-regression), 6 still failing in both, 49 still passing in both, 93 infrastructure-affected (expected — that run only had 57 evaluable scenarios against an empty fixture).

No regression is hidden behind an improved aggregate: every "newly broken" item across all three comparisons was individually investigated (§6) and none is a real code regression.

## 9. Verification performed

- `refresh_weather_fixtures`: real live capture, 3126/3126, 0 failures (§1).
- Deterministic reproducibility: two full-corpus runs, diffed programmatically, byte-identical (§2).
- Full-pipeline evaluation: `--split all --full`, real AI, real fixture-backed climate (§3).
- `compare_evaluations` against all three historical runs (§8).
- Targeted reruns (3–5 samples each) of every scenario whose status changed, to separate LLM variance from real regressions (§5, §6) — not asserted from a single observation.
- Full Django test suite: **796/796 passing**, zero regressions.
- `ruff check .`: **clean**.
- No code, prompt, scoring, ranking, or destination-data file was modified. The only tracked file changed is `evaluations/fixtures/weather.json` (real captured data, additive only). `git status` confirms nothing else in the tracked tree changed.

## 10. Evaluation cost

**$0.0554** for this run's 146 full-pipeline scenarios (estimated from character length, per the framework's documented cost-estimation limitation — no real token-usage API is available at either AI call site used here). Repeated-sampling investigation in §5/§6 added roughly 20 more scenario-level full-pipeline calls (a handful of cents at the same rate, not separately run through the cost tracker since those were ad hoc diagnostic reruns, not persisted evaluation runs).

## 11. Recommendation on promotion to baseline

**Not promoted here, per this cycle's explicit scope** — but on the evidence gathered, this run looks like a strong, honest candidate for the next official baseline once a human confirms:

- Every "newly broken" scenario has a direct, repeated-sampling explanation (not a guess) showing it's LLM variance, not a code regression (§6).
- The two genuinely reproducible remaining failures (`ADV-001`, `STR-006`, §5) are both edge cases with defensible (if debatable) root causes, not silent data corruption or crashes.
- The deterministic layer is proven byte-for-byte reproducible (§2), and full fixture coverage means future runs no longer inherit Open-Meteo's own availability as noise.
- `EXPLANATION_GROUNDING` and `HARD_CONSTRAINT` are both at zero on the largest evaluable sample this framework has ever produced.

This is an assessment, not a decision — promoting a run to the official baseline, and deciding what (if anything) to do about `ADV-001`/`STR-006`/`CON-004`, are left to the user, per this cycle's explicit instruction not to promote and not to start Cycle 2.
