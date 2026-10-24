SELECT
    entity_id
FROM cache_v4_source_entries
WHERE source_id = ?
ORDER BY source_index
