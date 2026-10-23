CREATE TABLE IF NOT EXISTS source_coverage (
    source_url TEXT PRIMARY KEY,
    source_kind TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    observed_entries INTEGER NOT NULL,
    cached_entries INTEGER NOT NULL,
    complete INTEGER NOT NULL,
    reason TEXT NOT NULL
)
