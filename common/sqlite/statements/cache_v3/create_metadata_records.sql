CREATE TABLE IF NOT EXISTS metadata_records (
    source_url TEXT NOT NULL,
    video_id TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    PRIMARY KEY (source_url, video_id)
)
