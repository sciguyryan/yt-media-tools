SELECT
    entity_id,
    service,
    external_id
FROM cache_v4_media_entities
WHERE service = ? AND external_id = ?;
