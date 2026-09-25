# Wanderes Recommendation Evaluation

- Run: `20260925-155531_cycle1_verified` (full mode)
- Corpus version: `v1`
- Git commit: `None`
- Scenarios: 150 total, 57 evaluable, 93 infrastructure failure(s)
- Quality result: 51/57 evaluable scenarios passed (89.5%)
- Raw (unfiltered) result: 51/150 passed
- Estimated cost: $0.0187 (57 pipeline calls, 0 judge calls)

## Failure taxonomy

- DEPENDENCY_FAILURE: 93
- INTENT_EXTRACTION: 6
- SCORING: 1

## Dev split: 44/49 evaluable passed, 78 infrastructure failure(s)

## Holdout split: 7/8 evaluable passed, 15 infrastructure failure(s)

## Intent extraction accuracy (by field)

- `continent`: 100%
- `country`: 100%
- `excluded_place_names`: 100%
- `max_cost_of_living`: 100%
- `month`: 100%
- `trip_type`: 100%

## Infrastructure failures (excluded from quality result above)

- `ADV-001` (adversarial): EVALUATION_INFRASTRUCTURE: missing weather fixture for (-8.34, 115.09, month=1) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `ADV-003` (adversarial): EVALUATION_INFRASTRUCTURE: missing weather fixture for (-8.34, 115.09, month=9) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `ADV-006` (adversarial): EVALUATION_INFRASTRUCTURE: missing weather fixture for (-8.34, 115.09, month=9) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `ADV-010` (adversarial): EVALUATION_INFRASTRUCTURE: missing weather fixture for (-8.34, 115.09, month=9) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `AMB-008` (ambiguous): EVALUATION_INFRASTRUCTURE: missing weather fixture for (64.15, -21.94, month=9) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `AMB-009` (ambiguous): EVALUATION_INFRASTRUCTURE: missing weather fixture for (38.72, -9.14, month=6) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `AMB-012` (ambiguous): EVALUATION_INFRASTRUCTURE: missing weather fixture for (35.01, 135.77, month=9) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `CON-001` (conflicting): EVALUATION_INFRASTRUCTURE: missing weather fixture for (-8.34, 115.09, month=9) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `CON-002` (conflicting): EVALUATION_INFRASTRUCTURE: missing weather fixture for (-8.34, 115.09, month=9) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `CON-003` (conflicting): EVALUATION_INFRASTRUCTURE: missing weather fixture for (38.72, -9.14, month=9) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `CON-005` (conflicting): EVALUATION_INFRASTRUCTURE: missing weather fixture for (38.12, 13.36, month=9) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `CON-006` (conflicting): EVALUATION_INFRASTRUCTURE: missing weather fixture for (-8.34, 115.09, month=9) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `CON-009` (conflicting): EVALUATION_INFRASTRUCTURE: missing weather fixture for (35.01, 135.77, month=9) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `CON-010` (conflicting): EVALUATION_INFRASTRUCTURE: missing weather fixture for (-8.34, 115.09, month=9) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `INC-003` (incomplete): EVALUATION_INFRASTRUCTURE: missing weather fixture for (-8.34, 115.09, month=9) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `INC-004` (incomplete): EVALUATION_INFRASTRUCTURE: missing weather fixture for (38.72, -9.14, month=9) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `INC-008` (incomplete): EVALUATION_INFRASTRUCTURE: missing weather fixture for (35.01, 135.77, month=9) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `INC-013` (incomplete): EVALUATION_INFRASTRUCTURE: missing weather fixture for (64.15, -21.94, month=9) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `MET-001a` (metamorphic): EVALUATION_INFRASTRUCTURE: missing weather fixture for (-8.34, 115.09, month=7) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `MET-001b` (metamorphic): EVALUATION_INFRASTRUCTURE: missing weather fixture for (-8.34, 115.09, month=7) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `MET-002a` (metamorphic): EVALUATION_INFRASTRUCTURE: missing weather fixture for (38.12, 13.36, month=10) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `MET-002b` (metamorphic): EVALUATION_INFRASTRUCTURE: missing weather fixture for (44.84, -0.58, month=10) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `MET-003a` (metamorphic): EVALUATION_INFRASTRUCTURE: missing weather fixture for (-13.53, -71.97, month=3) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `MET-003b` (metamorphic): EVALUATION_INFRASTRUCTURE: missing weather fixture for (-13.53, -71.97, month=3) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `MET-004a` (metamorphic): EVALUATION_INFRASTRUCTURE: missing weather fixture for (-8.34, 115.09, month=7) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `MET-004b` (metamorphic): EVALUATION_INFRASTRUCTURE: missing weather fixture for (-8.34, 115.09, month=7) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `MET-005a` (metamorphic): EVALUATION_INFRASTRUCTURE: missing weather fixture for (38.72, -9.14, month=9) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `MET-005b` (metamorphic): EVALUATION_INFRASTRUCTURE: missing weather fixture for (38.72, -9.14, month=9) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `MET-006a` (metamorphic): EVALUATION_INFRASTRUCTURE: missing weather fixture for (44.84, -0.58, month=5) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `MET-006b` (metamorphic): EVALUATION_INFRASTRUCTURE: missing weather fixture for (41.9, 12.5, month=5) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `MET-007a` (metamorphic): EVALUATION_INFRASTRUCTURE: missing weather fixture for (-8.34, 115.09, month=2) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `MET-007b` (metamorphic): EVALUATION_INFRASTRUCTURE: missing weather fixture for (7.88, 98.39, month=2) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `MET-008a` (metamorphic): EVALUATION_INFRASTRUCTURE: missing weather fixture for (18.79, 98.98, month=10) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `MET-008b` (metamorphic): EVALUATION_INFRASTRUCTURE: missing weather fixture for (15.88, 108.34, month=10) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `MET-009a` (metamorphic): EVALUATION_INFRASTRUCTURE: missing weather fixture for (-13.53, -71.97, month=6) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `MET-009b` (metamorphic): EVALUATION_INFRASTRUCTURE: missing weather fixture for (-25.6, -54.59, month=6) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `MET-010a` (metamorphic): EVALUATION_INFRASTRUCTURE: missing weather fixture for (64.15, -21.94, month=7) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `MET-010b` (metamorphic): EVALUATION_INFRASTRUCTURE: missing weather fixture for (64.15, -21.94, month=12) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `MTT-002` (multi_turn): EVALUATION_INFRASTRUCTURE: missing weather fixture for (44.84, -0.58, month=5) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `MTT-003` (multi_turn): EVALUATION_INFRASTRUCTURE: missing weather fixture for (-13.53, -71.97, month=6) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `MTT-007` (multi_turn): EVALUATION_INFRASTRUCTURE: missing weather fixture for (-8.34, 115.09, month=10) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `MTT-010` (multi_turn): EVALUATION_INFRASTRUCTURE: missing weather fixture for (-8.34, 115.09, month=10) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `ROB-001` (robustness): EVALUATION_INFRASTRUCTURE: missing weather fixture for (39.9, 116.41, month=10) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `ROB-003` (robustness): EVALUATION_INFRASTRUCTURE: missing weather fixture for (-8.34, 115.09, month=7) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `ROB-012` (robustness): EVALUATION_INFRASTRUCTURE: missing weather fixture for (35.01, 135.77, month=4) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `ROB-013` (robustness): EVALUATION_INFRASTRUCTURE: missing weather fixture for (-8.34, 115.09, month=7) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `ROB-014` (robustness): EVALUATION_INFRASTRUCTURE: missing weather fixture for (-13.53, -71.97, month=7) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `ROB-015` (robustness): EVALUATION_INFRASTRUCTURE: missing weather fixture for (38.72, -9.14, month=7) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `ROB-016` (robustness): EVALUATION_INFRASTRUCTURE: missing weather fixture for (-8.34, 115.09, month=7) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- `STR-001` (straightforward): EVALUATION_INFRASTRUCTURE: missing weather fixture for (-8.34, 115.09, month=7) - run `python manage.py refresh_weather_fixtures` to capture it (requires live Open-Meteo access).
- ... and 43 more (see results.jsonl)

## Failed scenarios (quality)

- `ADV-008` (adversarial): flow_mismatch
- `CON-004` (conflicting): flow_mismatch
- `INC-010` (incomplete): flow_mismatch
- `MTT-006` (multi_turn): flow_mismatch
- `MTT-008` (multi_turn): flow_mismatch
- `STR-006` (straightforward): flow_mismatch, winner_in_acceptable_set
