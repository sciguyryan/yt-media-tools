SELECT
    1
WHERE EXISTS (
    SELECT
        1
    FROM cache_v4_source_entries
    WHERE entity_id = ?
);
