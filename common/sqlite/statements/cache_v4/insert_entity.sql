INSERT INTO cache_v4_media_entities (service, external_id)
VALUES (?, ?)
ON CONFLICT (service, external_id) DO NOTHING;
