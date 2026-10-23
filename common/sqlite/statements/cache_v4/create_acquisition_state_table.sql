CREATE TABLE IF NOT EXISTS cache_v4_acquisition_state (
    entity_id INTEGER NOT NULL REFERENCES cache_v4_media_entities (entity_id) ON DELETE CASCADE,
    provider_id INTEGER NOT NULL REFERENCES cache_v4_providers (provider_id),
    acquisition_group_id INTEGER NOT NULL REFERENCES cache_v4_acquisition_groups (acquisition_group_id),
    outcome TEXT NOT NULL CHECK (outcome IN ('success', 'failed')),
    last_attempt_at TEXT NOT NULL,
    last_success_at TEXT,
    failure_category TEXT,
    PRIMARY KEY (entity_id, provider_id, acquisition_group_id),
    CHECK (
        (outcome = 'success' AND last_success_at = last_attempt_at AND failure_category IS NULL)
        OR (
            outcome = 'failed' AND failure_category IS NOT NULL
            AND (last_success_at IS NULL OR last_success_at <= last_attempt_at)
        )
    )
)
