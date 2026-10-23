CREATE TABLE IF NOT EXISTS cache_v4_media_entities (
    entity_id INTEGER PRIMARY KEY,
    service TEXT NOT NULL,
    external_id TEXT NOT NULL,
    UNIQUE (service, external_id)
)
