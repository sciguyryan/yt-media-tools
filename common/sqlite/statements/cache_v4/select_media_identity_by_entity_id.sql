SELECT
    service,
    external_id
FROM cache_v4_media_entities
WHERE entity_id = ?
