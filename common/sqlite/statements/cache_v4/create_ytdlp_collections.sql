CREATE TABLE cache_v4_ytdlp_collections (
    entity_id INTEGER PRIMARY KEY REFERENCES cache_v4_media_entities (entity_id) ON DELETE CASCADE,
    tags_json TEXT,
    categories_json TEXT,
    formats_json TEXT,
    chapters_json TEXT,
    thumbnails_json TEXT
);
