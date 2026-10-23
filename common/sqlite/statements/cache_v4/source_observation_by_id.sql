SELECT
    last_observed_at,
    observed_entries
FROM cache_v4_source_observations
WHERE source_id = ?
