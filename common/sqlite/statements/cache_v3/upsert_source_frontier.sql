INSERT INTO source_frontiers (
    source_url, source_kind, verified_at, known_entries, head_video_id, overlap_confirmations
) VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT (source_url) DO UPDATE SET
source_kind = excluded.source_kind,
verified_at = excluded.verified_at,
known_entries = excluded.known_entries,
head_video_id = excluded.head_video_id,
overlap_confirmations = excluded.overlap_confirmations;
