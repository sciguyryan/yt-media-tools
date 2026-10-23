INSERT OR IGNORE INTO source_frontiers (
    source_url, source_kind, verified_at, known_entries, head_video_id, overlap_confirmations
) VALUES (?, ?, ?, ?, ?, 0)
