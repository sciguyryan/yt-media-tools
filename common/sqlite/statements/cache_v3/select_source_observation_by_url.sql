SELECT
    last_observed_at,
    observed_entries
FROM source_observations
WHERE source_url = ?
