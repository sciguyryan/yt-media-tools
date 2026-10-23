INSERT INTO cache_v4_acquisition_state (
    entity_id, provider_id, acquisition_group_id, outcome,
    last_attempt_at, last_success_at, failure_category
) VALUES (?, ?, ?, 'failed', ?, NULL, ?)
ON CONFLICT (entity_id, provider_id, acquisition_group_id) DO UPDATE SET
    outcome = 'failed',
    last_attempt_at = excluded.last_attempt_at,
    failure_category = excluded.failure_category
