INSERT INTO cache_v4_ytdlp_collections (
    entity_id,
    tags_json,
    categories_json,
    formats_json,
    chapters_json,
    thumbnails_json
)
VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT (entity_id) DO UPDATE SET
tags_json = excluded.tags_json,
categories_json = excluded.categories_json,
formats_json = excluded.formats_json,
chapters_json = excluded.chapters_json,
thumbnails_json = excluded.thumbnails_json;
