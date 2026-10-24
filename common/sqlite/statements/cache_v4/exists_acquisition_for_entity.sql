SELECT 1
WHERE EXISTS (
    SELECT 1
    FROM cache_v4_acquisition_state
    WHERE entity_id = ?
)
