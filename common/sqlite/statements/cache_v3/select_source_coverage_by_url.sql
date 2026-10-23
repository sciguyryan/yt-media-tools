SELECT
    observed_at,
    observed_entries,
    cached_entries,
    complete,
    reason
FROM source_coverage
WHERE source_url = ?
