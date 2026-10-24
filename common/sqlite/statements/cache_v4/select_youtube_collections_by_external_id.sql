SELECT
    tags_json,
    categories_json,
    formats_json,
    chapters_json,
    thumbnails_json
FROM cache_v4_ytdlp_collections
WHERE entity_id = (
    SELECT
        e.entity_id
    FROM cache_v4_media_entities AS e
    WHERE e.service = 'youtube' AND e.external_id = ?
);
