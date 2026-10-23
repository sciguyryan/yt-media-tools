INSERT INTO cache_v4_sources (source_url, source_kind, facet)
VALUES (?, ?, ?)
ON CONFLICT (source_url, facet) DO UPDATE SET source_kind = excluded.source_kind
