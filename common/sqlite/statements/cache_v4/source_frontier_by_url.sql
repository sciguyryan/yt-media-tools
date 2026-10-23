SELECT
    s.source_kind,
    f.verified_at,
    f.known_entries,
    e.external_id,
    f.overlap_confirmations
FROM cache_v4_sources AS s
INNER JOIN cache_v4_source_frontiers AS f ON s.source_id = f.source_id
INNER JOIN cache_v4_media_entities AS e ON f.head_entity_id = e.entity_id
WHERE s.source_url = ? AND s.facet = '';
