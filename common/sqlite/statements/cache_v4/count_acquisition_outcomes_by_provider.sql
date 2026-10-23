SELECT
    COUNT(*) AS total_count,
    SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END) AS success_count,
    SUM(CASE WHEN outcome = 'failed' THEN 1 ELSE 0 END) AS failed_count
FROM cache_v4_acquisition_state
WHERE provider_id = ?;
