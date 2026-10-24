SELECT
    source_index
FROM source_entries
WHERE source_url = ?
ORDER BY source_index, video_id
