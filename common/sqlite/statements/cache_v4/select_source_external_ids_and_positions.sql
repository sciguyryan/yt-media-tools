SELECT
    e.external_id,
    se.source_index
FROM cache_v4_source_entries AS se
INNER JOIN cache_v4_media_entities AS e
    ON se.entity_id = e.entity_id
WHERE se.source_id = ?
ORDER BY se.source_index, e.external_id;
