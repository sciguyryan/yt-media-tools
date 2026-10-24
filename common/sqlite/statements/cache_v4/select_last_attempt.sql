SELECT
    last_attempt_at
FROM cache_v4_acquisition_state
WHERE entity_id = ? AND provider_id = ? AND acquisition_group_id = ?;
