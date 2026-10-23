SELECT
    source_url,
    video_id,
    fetched_at,
    raw_json
FROM metadata_records
ORDER BY fetched_at, source_url, video_id;
