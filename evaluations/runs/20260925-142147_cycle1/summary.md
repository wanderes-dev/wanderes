# Wanderes Recommendation Evaluation

- Run: `20260925-142147_cycle1` (full mode)
- Corpus version: `v1`
- Git commit: `None`
- Scenarios: 150 (129 passed, 21 failed)
- Estimated cost: $0.0581 (150 pipeline calls, 0 judge calls)

## Failure taxonomy

- INTENT_EXTRACTION: 12
- SCORING: 8
- EXPLANATION_GROUNDING: 4

## Dev split: 108/127 passed

## Holdout split: 21/23 passed

## Intent extraction accuracy (by field)

- `continent`: 100%
- `country`: 96%
- `excluded_place_names`: 100%
- `max_cost_of_living`: 100%
- `max_temp_c`: 100%
- `min_temp_c`: 75%
- `month`: 100%
- `trip_type`: 96%

## Failed scenarios

- `ADV-001` (adversarial): zero_results_expectation
- `ADV-008` (adversarial): flow_mismatch
- `AMB-001` (ambiguous): intent_field:trip_type
- `CON-002` (conflicting): flow_mismatch
- `CON-004` (conflicting): flow_mismatch
- `INC-010` (incomplete): flow_mismatch
- `MET-006b` (metamorphic): winner_mentioned
- `MTT-006` (multi_turn): flow_mismatch
- `MTT-008` (multi_turn): flow_mismatch
- `MTT-010` (multi_turn): intent_field:trip_type, intent_field:country, winner_mentioned
- `STR-004` (straightforward): winner_mentioned
- `STR-005` (straightforward): winner_in_acceptable_set
- `STR-006` (straightforward): flow_mismatch, winner_in_acceptable_set
- `STR-012` (straightforward): winner_mentioned
- `STR-016` (straightforward): winner_in_acceptable_set
- `STR-019` (straightforward): winner_in_acceptable_set
- `STR-027` (straightforward): intent_field:trip_type
- `STR-037` (straightforward): intent_field:min_temp_c
- `STR-041` (straightforward): winner_in_acceptable_set
- `STR-052` (straightforward): winner_in_acceptable_set
- `STR-054` (straightforward): winner_in_acceptable_set

## Metamorphic pairs

10 pairs run, 0 with a failed structural check.
