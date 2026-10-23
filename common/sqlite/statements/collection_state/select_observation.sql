SELECT
    fingerprint_version,
    sequence_fingerprint,
    target_count
FROM collection_observations
WHERE collection_id = ?;
