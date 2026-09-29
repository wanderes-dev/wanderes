# Wanderes Recommendation Evaluation

- Run: `20260928-164649_cycle2_improvement1_singleturn_check_v5` (full mode)
- Corpus version: `v1`
- Git commit: `None`
- Scenarios: 150 total, 150 evaluable, 0 infrastructure failure(s)
- Quality result: 133/150 evaluable scenarios passed (88.7%)
- Raw (unfiltered) result: 133/150 passed
- Estimated cost: $0.0567 (150 pipeline calls, 0 judge calls)

## Failure taxonomy

- INTENT_EXTRACTION: 15
- SCORING: 3

## Dev split: 113/127 evaluable passed

## Holdout split: 20/23 evaluable passed

## Intent extraction accuracy (by field)

- `continent`: 100%
- `country`: 100%
- `excluded_place_names`: 100%
- `max_cost_of_living`: 94%
- `max_temp_c`: 100%
- `min_temp_c`: 75%
- `month`: 100%
- `trip_type`: 96%

## Failed scenarios (quality)

- `ADV-001` (adversarial): zero_results_expectation
- `ADV-008` (adversarial): flow_mismatch
- `AMB-012` (ambiguous): intent_field:trip_type
- `CON-002` (conflicting): flow_mismatch
- `CON-004` (conflicting): flow_mismatch
- `INC-010` (incomplete): flow_mismatch
- `MTT-006` (multi_turn): flow_mismatch
- `MTT-008` (multi_turn): flow_mismatch
- `MTT-010` (multi_turn): intent_field:trip_type
- `ROB-002` (robustness): flow_mismatch
- `STR-001` (straightforward): intent_field:max_cost_of_living
- `STR-006` (straightforward): flow_mismatch, winner_in_acceptable_set
- `STR-026` (straightforward): intent_field:max_cost_of_living
- `STR-027` (straightforward): intent_field:trip_type
- `STR-037` (straightforward): intent_field:min_temp_c
- `STR-049` (straightforward): intent_field:max_cost_of_living
- `STR-052` (straightforward): winner_in_acceptable_set

## Metamorphic pairs

10 pairs run, 0 with a failed structural check.
