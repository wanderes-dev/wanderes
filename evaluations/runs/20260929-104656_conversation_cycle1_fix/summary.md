# Wanderes Multi-Turn Conversation Evaluation

- Run: `20260929-104656_conversation_cycle1_fix`
- Corpus version: `v1`
- Git commit: `None`
- Conversations: 53 total, 53 evaluable, 0 infrastructure failure(s)
- Full-conversation pass rate: 29/53 (54.7%)
- Checkpoint pass rate: 83/120
- Estimated cost: $0.0602 (137 turn calls)

## State-transition metrics

- Retained-field accuracy: 77.3% (n=194)
- Correction accuracy: 94.7% (n=19)
- Supersession accuracy: 82.8% (n=29)
- Exclusion-persistence accuracy: 88.2% (n=17)
- Contradiction-resolution accuracy: 92.9% (n=14)
- Reference-resolution accuracy: 100.0% (n=10)
- Irrelevant-information stability: 35.0% (n=20)

## Failure taxonomy

- LOST_CONTEXT: 42
- INTENT_EXTRACTION: 19
- EXCLUSION_PERSISTENCE: 2
- CORRECTION_FAILURE: 1
- CONTRADICTION_RESOLUTION: 1
- EXPLANATION_GROUNDING: 1

## By split

- dev: 25/45 (55.6%)
- holdout: 4/8 (50.0%)

## By family

- contradiction: 6/7 (85.7%)
- correction: 8/9 (88.9%)
- cross_family: 1/7 (14.3%)
- drift: 3/7 (42.9%)
- irrelevant_info: 0/9 (0.0%)
- memory: 4/7 (57.1%)
- reference: 7/7 (100.0%)

## Failed conversations (quality)

- `DRIFT-001` (drift): checkpoint_state:min_temp_c, checkpoint_state:min_temp_c, checkpoint_state:trip_type
- `DRIFT-003` (drift): checkpoint_state:min_temp_c
- `DRIFT-004` (drift): checkpoint_state:max_cost_of_living
- `DRIFT-007` (drift): checkpoint_state:max_cost_of_living
- `CORR-003` (correction): checkpoint_state:max_cost_of_living
- `CONTRA-005` (contradiction): checkpoint_state:trip_type
- `MEM-001` (memory): checkpoint_state:trip_type, checkpoint_state:trip_type
- `MEM-002` (memory): checkpoint_state:excluded_slugs, checkpoint_state:excluded_slugs
- `MEM-005` (memory): checkpoint_state:trip_type
- `IRR-001` (irrelevant_info): checkpoint_state:trip_type, checkpoint_state:country, no_lost_context
- `IRR-002` (irrelevant_info): checkpoint_state:trip_type, checkpoint_state:country, no_lost_context
- `IRR-003` (irrelevant_info): checkpoint_state:trip_type, checkpoint_state:max_cost_of_living, no_lost_context
- `IRR-004` (irrelevant_info): checkpoint_state:trip_type, checkpoint_state:country, no_lost_context
- `IRR-005` (irrelevant_info): checkpoint_state:trip_type, checkpoint_state:country, checkpoint_state:trip_type, checkpoint_state:country, no_lost_context
- `IRR-006` (irrelevant_info): checkpoint_state:trip_type, checkpoint_state:max_cost_of_living, checkpoint_state:month, no_lost_context
- `IRR-007` (irrelevant_info): checkpoint_state:trip_type, no_lost_context
- `XFAM-001` (cross_family): checkpoint_state:trip_type, checkpoint_state:max_cost_of_living, checkpoint_state:month, checkpoint_state:max_cost_of_living, checkpoint_state:excluded_slugs, no_lost_context
- `XFAM-002` (cross_family): checkpoint_state:trip_type, checkpoint_state:continent, checkpoint_state:excluded_slugs, exclusion_still_persists, no_lost_context
- `XFAM-003` (cross_family): checkpoint_state:max_cost_of_living, checkpoint_state:excluded_slugs, checkpoint_state:max_cost_of_living, checkpoint_state:excluded_slugs, exclusion_still_persists, no_lost_context
- `XFAM-004` (cross_family): checkpoint_state:trip_type, checkpoint_state:trip_type, no_lost_context
- `XFAM-005` (cross_family): checkpoint_state:max_cost_of_living
- `XFAM-007` (cross_family): checkpoint_state:max_cost_of_living, checkpoint_state:max_cost_of_living
- `CMET-001a` (irrelevant_info): checkpoint_state:max_cost_of_living, checkpoint_state:max_cost_of_living, winner_mentioned
- `CMET-001b` (irrelevant_info): checkpoint_state:max_cost_of_living, checkpoint_state:max_cost_of_living, checkpoint_state:max_cost_of_living, no_lost_context
