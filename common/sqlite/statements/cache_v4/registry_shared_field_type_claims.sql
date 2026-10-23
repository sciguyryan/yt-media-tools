SELECT
    f.field_name,
    f.type_json,
    p.provider_key
FROM cache_v4_fields AS f
INNER JOIN cache_v4_providers AS p ON f.provider_id = p.provider_id
WHERE f.declared = 1 AND p.declared = 1
ORDER BY f.field_name, p.registration_order
