INSERT INTO source_observations (source_url, source_kind, last_observed_at, observed_entries)
VALUES (?, ?, ?, ?)
ON CONFLICT (source_url) DO UPDATE SET
source_kind = excluded.source_kind,
last_observed_at = excluded.last_observed_at,
observed_entries = excluded.observed_entries;
