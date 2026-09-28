# Wanderes Recommendation Evaluation

- Run: `20260928-090035_cycle1_verified_full` (full mode)
- Corpus version: `v1`
- Git commit: `None`
- Scenarios: 150 total, 146 evaluable, 4 infrastructure failure(s)
- Quality result: 132/146 evaluable scenarios passed (90.4%)
- Raw (unfiltered) result: 132/150 passed
- Estimated cost: $0.0554 (146 pipeline calls, 0 judge calls)

## Failure taxonomy

- INTENT_EXTRACTION: 13
- DEPENDENCY_FAILURE: 4
- SCORING: 2

## Dev split: 113/124 evaluable passed, 3 infrastructure failure(s)

## Holdout split: 19/22 evaluable passed, 1 infrastructure failure(s)

## Intent extraction accuracy (by field)

- `continent`: 100%
- `country`: 100%
- `excluded_place_names`: 100%
- `max_cost_of_living`: 98%
- `max_temp_c`: 100%
- `min_temp_c`: 75%
- `month`: 100%
- `trip_type`: 97%

## Infrastructure failures (excluded from quality result above)

- `MET-003b` (metamorphic): EVALUATION_INFRASTRUCTURE: missing weather fixture for (51.18, -115.57, month=3) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `MTT-007` (multi_turn): EVALUATION_INFRASTRUCTURE: missing weather fixture for (36.39, 25.46, month=10) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `MTT-010` (multi_turn): EVALUATION_INFRASTRUCTURE: missing weather fixture for (35.01, 135.77, month=10) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `ROB-015` (robustness): EVALUATION_INFRASTRUCTURE: missing weather fixture for (38.72, -9.14, month=7) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).

## Failed scenarios (quality)

- `ADV-001` (adversarial): zero_results_expectation
- `ADV-008` (adversarial): flow_mismatch
- `AMB-012` (ambiguous): intent_field:trip_type
- `CON-002` (conflicting): flow_mismatch
- `CON-004` (conflicting): flow_mismatch
- `INC-010` (incomplete): flow_mismatch
- `MTT-006` (multi_turn): flow_mismatch
- `MTT-008` (multi_turn): flow_mismatch
- `ROB-002` (robustness): flow_mismatch
- `ROB-017` (robustness): flow_mismatch
- `STR-006` (straightforward): flow_mismatch, winner_in_acceptable_set
- `STR-027` (straightforward): intent_field:trip_type
- `STR-037` (straightforward): intent_field:min_temp_c
- `STR-049` (straightforward): intent_field:max_cost_of_living

## Metamorphic pairs

10 pairs run, 0 with a failed structural check.
