SELECT
    fetched_at,
    raw_json
FROM metadata_records
WHERE source_url = ? AND video_id = ?;
