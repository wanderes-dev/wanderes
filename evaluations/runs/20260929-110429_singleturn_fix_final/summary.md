# Wanderes Recommendation Evaluation

- Run: `20260929-110429_singleturn_fix_final` (full mode)
- Corpus version: `v1`
- Git commit: `None`
- Scenarios: 150 total, 150 evaluable, 0 infrastructure failure(s)
- Quality result: 138/150 evaluable scenarios passed (92.0%)
- Raw (unfiltered) result: 138/150 passed
- Estimated cost: $0.0669 (150 pipeline calls, 0 judge calls)

## Failure taxonomy

- INTENT_EXTRACTION: 11
- SCORING: 2
- EXPLANATION_GROUNDING: 1

## Dev split: 117/127 evaluable passed

## Holdout split: 21/23 evaluable passed

## Intent extraction accuracy (by field)

- `continent`: 100%
- `country`: 96%
- `excluded_place_names`: 100%
- `max_cost_of_living`: 100%
- `max_temp_c`: 100%
- `min_temp_c`: 75%
- `month`: 100%
- `trip_type`: 97%

## Failed scenarios (quality)

- `ADV-001` (adversarial): zero_results_expectation
- `ADV-008` (adversarial): flow_mismatch
- `CON-002` (conflicting): flow_mismatch
- `CON-004` (conflicting): flow_mismatch
- `INC-010` (incomplete): flow_mismatch
- `MTT-006` (multi_turn): flow_mismatch
- `MTT-008` (multi_turn): flow_mismatch
- `MTT-010` (multi_turn): intent_field:trip_type, intent_field:country
- `STR-006` (straightforward): flow_mismatch, winner_in_acceptable_set
- `STR-023` (straightforward): winner_mentioned
- `STR-027` (straightforward): intent_field:trip_type
- `STR-037` (straightforward): intent_field:min_temp_c

## Metamorphic pairs

10 pairs run, 0 with a failed structural check.
