SELECT 1
WHERE EXISTS (
    SELECT 1
    FROM cache_v4_source_frontiers
    WHERE head_entity_id = ?
)
