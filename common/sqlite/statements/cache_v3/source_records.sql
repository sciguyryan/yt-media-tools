SELECT
    m.video_id,
    m.fetched_at,
    m.raw_json
FROM metadata_records AS m
LEFT JOIN source_entries AS s
    ON m.source_url = s.source_url AND m.video_id = s.video_id
WHERE m.source_url = ?
ORDER BY CASE WHEN s.source_index IS NULL THEN 1 ELSE 0 END, s.source_index, m.video_id;
