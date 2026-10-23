INSERT INTO cache_v4_source_frontiers (
    source_id, verified_at, known_entries, head_entity_id, overlap_confirmations
) VALUES (?, ?, ?, ?, ?)
ON CONFLICT (source_id) DO UPDATE SET
verified_at = excluded.verified_at,
known_entries = excluded.known_entries,
head_entity_id = excluded.head_entity_id,
overlap_confirmations = excluded.overlap_confirmations
