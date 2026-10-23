INSERT INTO metadata_records (source_url, video_id, fetched_at, raw_json)
VALUES (?, ?, ?, ?)
ON CONFLICT (source_url, video_id) DO UPDATE SET
    fetched_at = excluded.fetched_at,
    raw_json = excluded.raw_json;
