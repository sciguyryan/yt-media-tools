INSERT INTO cache_v4_source_coverage (
    source_id, observed_at, observed_entries, cached_entries, complete, reason
) VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT (source_id) DO UPDATE SET
observed_at = excluded.observed_at,
observed_entries = excluded.observed_entries,
cached_entries = excluded.cached_entries,
complete = excluded.complete,
reason = excluded.reason
