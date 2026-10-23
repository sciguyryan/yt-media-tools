SELECT
    f.field_name,
    f.freshness_mode_override,
    f.max_age_seconds_override
FROM cache_v4_fields AS f
INNER JOIN cache_v4_providers AS p ON f.provider_id = p.provider_id
WHERE p.provider_key = ? AND f.freshness_mode_override IS NOT NULL
ORDER BY f.registration_order
