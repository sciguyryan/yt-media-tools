SELECT
    outcome,
    last_attempt_at,
    last_success_at,
    failure_category
FROM cache_v4_acquisition_state
WHERE entity_id = ? AND provider_id = ? AND acquisition_group_id = ?
