SELECT
    f.field_id
FROM cache_v4_fields AS f
INNER JOIN cache_v4_providers AS p ON f.provider_id = p.provider_id
WHERE p.provider_key = ? AND f.field_name = ?
