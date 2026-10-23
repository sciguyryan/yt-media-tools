SELECT
    s.source_kind,
    c.observed_at,
    c.observed_entries,
    c.cached_entries,
    c.complete,
    c.reason
FROM cache_v4_sources AS s
INNER JOIN cache_v4_source_coverage AS c ON s.source_id = c.source_id
WHERE s.source_url = ? AND s.facet = '';
