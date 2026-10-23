SELECT
    f.verified_at,
    f.known_entries,
    e.external_id,
    f.overlap_confirmations
FROM cache_v4_source_frontiers AS f
INNER JOIN cache_v4_media_entities AS e
    ON f.head_entity_id = e.entity_id
WHERE f.source_id = ?;
