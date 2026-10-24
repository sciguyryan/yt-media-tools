SELECT COALESCE(MAX(registration_order), 0) + 1
FROM cache_v4_acquisition_groups
WHERE provider_id = ?
