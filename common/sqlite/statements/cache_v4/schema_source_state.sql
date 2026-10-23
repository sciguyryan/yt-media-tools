CREATE TABLE IF NOT EXISTS cache_v4_sources (
    source_id INTEGER PRIMARY KEY,
    source_url TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    facet TEXT NOT NULL DEFAULT '',
    UNIQUE (source_url, facet)
);

CREATE TABLE IF NOT EXISTS cache_v4_source_observations (
    source_id INTEGER PRIMARY KEY REFERENCES cache_v4_sources (source_id) ON DELETE CASCADE,
    last_observed_at TEXT NOT NULL,
    observed_entries INTEGER NOT NULL CHECK (observed_entries >= 0)
);

CREATE TABLE IF NOT EXISTS cache_v4_source_entries (
    source_id INTEGER NOT NULL REFERENCES cache_v4_sources (source_id) ON DELETE CASCADE,
    entity_id INTEGER NOT NULL REFERENCES cache_v4_media_entities (entity_id) ON DELETE RESTRICT,
    source_index INTEGER NOT NULL CHECK (source_index >= 0),
    PRIMARY KEY (source_id, entity_id),
    UNIQUE (source_id, source_index)
);

CREATE INDEX IF NOT EXISTS cache_v4_source_entries_entity
ON cache_v4_source_entries (entity_id);

CREATE TABLE IF NOT EXISTS cache_v4_source_coverage (
    source_id INTEGER PRIMARY KEY REFERENCES cache_v4_sources (source_id) ON DELETE CASCADE,
    observed_at TEXT NOT NULL,
    observed_entries INTEGER NOT NULL CHECK (observed_entries >= 0),
    cached_entries INTEGER NOT NULL CHECK (cached_entries >= 0),
    complete INTEGER NOT NULL CHECK (complete IN (0, 1)),
    reason TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cache_v4_source_frontiers (
    source_id INTEGER PRIMARY KEY REFERENCES cache_v4_sources (source_id) ON DELETE CASCADE,
    verified_at TEXT NOT NULL,
    known_entries INTEGER NOT NULL CHECK (known_entries >= 0),
    head_entity_id INTEGER NOT NULL REFERENCES cache_v4_media_entities (entity_id) ON DELETE RESTRICT,
    overlap_confirmations INTEGER NOT NULL CHECK (overlap_confirmations >= 0)
);
