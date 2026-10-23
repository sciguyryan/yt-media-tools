CREATE TABLE IF NOT EXISTS source_entries (
    source_url TEXT NOT NULL,
    video_id TEXT NOT NULL,
    source_index INTEGER NOT NULL,
    observed_at TEXT NOT NULL,
    PRIMARY KEY (source_url, video_id)
)
