SELECT
    provider_id,
    provider_key,
    registration_order,
    enabled,
    priority,
    schema_revision,
    metadata_table,
    applicability_json,
    declared
FROM cache_v4_providers
WHERE provider_key = ?;
