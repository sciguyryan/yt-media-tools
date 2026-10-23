CREATE TABLE IF NOT EXISTS source_observations (
    source_url TEXT PRIMARY KEY,
    source_kind TEXT NOT NULL,
    last_observed_at TEXT NOT NULL,
    observed_entries INTEGER NOT NULL DEFAULT 0
)
