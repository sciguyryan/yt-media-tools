SELECT
    verified_at,
    known_entries,
    head_video_id,
    overlap_confirmations
FROM source_frontiers
WHERE source_url = ?
