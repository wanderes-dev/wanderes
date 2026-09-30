# Wanderes Multi-Turn Conversation Evaluation

- Run: `20260930-110148_conversation_impr2_run1`
- Corpus version: `v1`
- Git commit: `None`
- Conversations: 53 total, 53 evaluable, 0 infrastructure failure(s)
- Full-conversation pass rate: 33/53 (62.3%)
- Checkpoint pass rate: 88/120
- Estimated cost: $0.0604 (137 turn calls)

## State-transition metrics

- Retained-field accuracy: 85.6% (n=194)
- Correction accuracy: 84.2% (n=19)
- Supersession accuracy: 69.0% (n=29)
- Exclusion-persistence accuracy: 94.1% (n=17)
- Contradiction-resolution accuracy: 78.6% (n=14)
- Reference-resolution accuracy: 90.0% (n=10)
- Irrelevant-information stability: 70.0% (n=20)

## Failure taxonomy

- INTENT_EXTRACTION: 21
- LOST_CONTEXT: 19
- EXPLANATION_GROUNDING: 2
- CORRECTION_FAILURE: 1
- CONTRADICTION_RESOLUTION: 1
- EXCLUSION_PERSISTENCE: 1
- REFERENCE_RESOLUTION: 1

## By split

- dev: 27/45 (60.0%)
- holdout: 6/8 (75.0%)

## By family

- contradiction: 5/7 (71.4%)
- correction: 7/9 (77.8%)
- cross_family: 2/7 (28.6%)
- drift: 2/7 (28.6%)
- irrelevant_info: 6/9 (66.7%)
- memory: 4/7 (57.1%)
- reference: 7/7 (100.0%)

## Failed conversations (quality)

- `DRIFT-001` (drift): checkpoint_state:min_temp_c, checkpoint_state:min_temp_c, checkpoint_state:trip_type
- `DRIFT-003` (drift): checkpoint_state:min_temp_c
- `DRIFT-004` (drift): checkpoint_state:max_cost_of_living
- `DRIFT-005` (drift): checkpoint_state:continent, checkpoint_state:continent, no_lost_context
- `DRIFT-007` (drift): checkpoint_state:max_cost_of_living
- `CORR-003` (correction): checkpoint_state:max_cost_of_living
- `CORR-004` (correction): checkpoint_state:country, checkpoint_state:country, no_lost_context
- `CONTRA-003` (contradiction): checkpoint_state:continent, checkpoint_state:continent, no_lost_context
- `CONTRA-004` (contradiction): checkpoint_state:min_temp_c
- `MEM-001` (memory): checkpoint_state:trip_type, checkpoint_state:trip_type, no_lost_context
- `MEM-002` (memory): checkpoint_state:excluded_slugs, checkpoint_state:excluded_slugs
- `MEM-005` (memory): checkpoint_state:trip_type, checkpoint_state:country
- `IRR-006` (irrelevant_info): checkpoint_state:month, no_lost_context
- `XFAM-001` (cross_family): checkpoint_state:month, checkpoint_state:max_cost_of_living, no_lost_context
- `XFAM-003` (cross_family): checkpoint_state:max_cost_of_living, checkpoint_state:excluded_slugs, checkpoint_state:max_cost_of_living, checkpoint_state:excluded_slugs, exclusion_still_persists, no_lost_context
- `XFAM-004` (cross_family): reference_resolved
- `XFAM-005` (cross_family): checkpoint_state:max_cost_of_living
- `XFAM-007` (cross_family): checkpoint_state:max_cost_of_living, checkpoint_state:max_cost_of_living
- `CMET-001a` (irrelevant_info): checkpoint_state:max_cost_of_living, checkpoint_state:max_cost_of_living, winner_mentioned
- `CMET-001b` (irrelevant_info): checkpoint_state:max_cost_of_living, checkpoint_state:max_cost_of_living, checkpoint_state:max_cost_of_living, winner_mentioned
