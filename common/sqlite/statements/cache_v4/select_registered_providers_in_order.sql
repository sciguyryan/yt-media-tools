SELECT
    provider_id,
    provider_key,
    schema_revision,
    metadata_table,
    declared,
    enabled,
    priority
FROM cache_v4_providers
ORDER BY registration_order
