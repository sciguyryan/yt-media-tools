INSERT INTO source_coverage (
    source_url, source_kind, observed_at, observed_entries,
    cached_entries, complete, reason
) VALUES (?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (source_url) DO UPDATE SET
    source_kind = excluded.source_kind,
    observed_at = excluded.observed_at,
    observed_entries = excluded.observed_entries,
    cached_entries = excluded.cached_entries,
    complete = excluded.complete,
    reason = excluded.reason;
