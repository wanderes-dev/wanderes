# Wanderes Recommendation Evaluation

- Run: `20260925-114531_baseline` (full mode)
- Corpus version: `v1`
- Git commit: `None`
- Scenarios: 150 (113 passed, 37 failed)
- Estimated cost: $0.0568 (150 pipeline calls, 0 judge calls)

## Failure taxonomy

- EXPLANATION_GROUNDING: 26
- INTENT_EXTRACTION: 13
- HARD_CONSTRAINT: 4
- SCORING: 2

## Dev split: 97/127 passed

## Holdout split: 16/23 passed

## Intent extraction accuracy (by field)

- `continent`: 100%
- `country`: 96%
- `excluded_place_names`: 25%
- `max_cost_of_living`: 100%
- `max_temp_c`: 100%
- `min_temp_c`: 75%
- `month`: 100%
- `trip_type`: 97%

## Failed scenarios

- `ADV-001` (adversarial): zero_results_expectation, winner_mentioned
- `ADV-003` (adversarial): winner_mentioned
- `ADV-007` (adversarial): intent_field:excluded_place_names
- `ADV-008` (adversarial): flow_mismatch
- `AMB-008` (ambiguous): winner_mentioned
- `AMB-009` (ambiguous): winner_mentioned
- `CON-002` (conflicting): flow_mismatch, winner_mentioned
- `CON-009` (conflicting): winner_mentioned
- `INC-003` (incomplete): winner_mentioned
- `INC-010` (incomplete): flow_mismatch
- `INC-013` (incomplete): winner_mentioned
- `MET-001a` (metamorphic): winner_mentioned
- `MET-001b` (metamorphic): winner_mentioned
- `MET-002b` (metamorphic): winner_mentioned
- `MET-006b` (metamorphic): winner_mentioned
- `MET-007a` (metamorphic): winner_mentioned
- `MTT-002` (multi_turn): intent_field:excluded_place_names, excluded_destinations_absent, must_not_include_absent
- `MTT-006` (multi_turn): flow_mismatch
- `MTT-008` (multi_turn): flow_mismatch
- `MTT-010` (multi_turn): intent_field:trip_type, intent_field:excluded_place_names, excluded_destinations_absent, must_not_include_absent
- `ROB-003` (robustness): winner_mentioned
- `ROB-013` (robustness): winner_mentioned
- `ROB-015` (robustness): winner_mentioned
- `ROB-016` (robustness): winner_mentioned
- `STR-006` (straightforward): flow_mismatch, winner_in_acceptable_set
- `STR-009` (straightforward): winner_mentioned
- `STR-010` (straightforward): winner_mentioned
- `STR-012` (straightforward): winner_mentioned
- `STR-024` (straightforward): winner_mentioned
- `STR-027` (straightforward): intent_field:trip_type
- `STR-030` (straightforward): winner_mentioned
- `STR-032` (straightforward): intent_field:country
- `STR-037` (straightforward): intent_field:min_temp_c
- `STR-045` (straightforward): winner_mentioned
- `STR-046` (straightforward): winner_mentioned
- `STR-049` (straightforward): winner_mentioned
- `STR-050` (straightforward): winner_mentioned

## Metamorphic pairs

10 pairs run, 0 with a failed structural check.
