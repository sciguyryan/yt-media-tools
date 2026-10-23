SELECT
    p.provider_id,
    p.provider_key,
    p.registration_order AS provider_registration_order,
    p.priority AS provider_priority,
    p.enabled,
    f.field_id,
    f.field_name,
    f.type_json,
    f.priority_override,
    f.default_freshness_mode,
    f.default_max_age_seconds,
    f.freshness_mode_override,
    f.max_age_seconds_override,
    g.acquisition_group_id,
    g.group_key
FROM cache_v4_fields AS f
INNER JOIN cache_v4_providers AS p ON f.provider_id = p.provider_id
INNER JOIN cache_v4_acquisition_groups AS g
    ON f.acquisition_group_id = g.acquisition_group_id
WHERE
    f.field_name = ?
    AND f.declared = 1
    AND p.declared = 1
    AND g.declared = 1
