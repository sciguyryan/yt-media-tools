INSERT INTO cache_v4_source_observations (source_id, last_observed_at, observed_entries)
VALUES (?, ?, ?)
ON CONFLICT (source_id) DO UPDATE SET
    last_observed_at = excluded.last_observed_at,
    observed_entries = excluded.observed_entries
