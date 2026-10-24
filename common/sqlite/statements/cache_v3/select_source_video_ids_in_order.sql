SELECT
    video_id
FROM source_entries
WHERE source_url = ?
ORDER BY source_index, video_id
