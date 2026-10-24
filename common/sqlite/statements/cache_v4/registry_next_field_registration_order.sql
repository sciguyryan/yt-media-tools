SELECT
    COALESCE(MAX(registration_order), 0) + 1
FROM cache_v4_fields
WHERE provider_id = ?
