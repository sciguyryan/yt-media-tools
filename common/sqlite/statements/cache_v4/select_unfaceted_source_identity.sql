SELECT
    source_id,
    source_kind,
    facet
FROM cache_v4_sources
WHERE source_url = ? AND facet = ''
