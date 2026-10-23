SELECT
    provider_id,
    provider_key,
    registration_order,
    enabled,
    priority,
    schema_revision
FROM cache_v4_providers
ORDER BY registration_order
