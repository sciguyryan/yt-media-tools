SELECT
    observed_at,
    observed_entries,
    cached_entries,
    complete,
    reason
FROM cache_v4_source_coverage
WHERE source_id = ?
