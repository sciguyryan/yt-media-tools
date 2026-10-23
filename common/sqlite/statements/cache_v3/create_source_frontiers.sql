CREATE TABLE IF NOT EXISTS source_frontiers (
    source_url TEXT PRIMARY KEY,
    source_kind TEXT NOT NULL,
    verified_at TEXT NOT NULL,
    known_entries INTEGER NOT NULL,
    head_video_id TEXT NOT NULL,
    overlap_confirmations INTEGER NOT NULL
)
