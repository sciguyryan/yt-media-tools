SELECT
    f.default_freshness_mode,
    f.default_max_age_seconds,
    f.freshness_mode_override,
    f.max_age_seconds_override
FROM cache_v4_fields AS f
INNER JOIN cache_v4_providers AS p
    ON f.provider_id = p.provider_id
WHERE
    p.provider_key = ?
    AND p.declared = 1
    AND f.field_name = ?
    AND f.declared = 1;
