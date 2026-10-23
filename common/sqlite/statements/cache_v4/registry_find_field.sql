SELECT
    field_id,
    provider_id,
    field_name,
    storage_name,
    acquisition_group_id,
    registration_order,
    type_json,
    default_freshness_mode,
    default_max_age_seconds,
    priority_override,
    freshness_mode_override,
    max_age_seconds_override,
    declared
FROM cache_v4_fields
WHERE provider_id = ? AND field_name = ?;
