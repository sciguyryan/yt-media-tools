SELECT
    provider_id,
    metadata_table
FROM cache_v4_providers
WHERE provider_key = ?;
