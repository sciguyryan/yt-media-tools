CREATE TABLE IF NOT EXISTS cache_v4_registry_meta (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    registry_schema_revision INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS cache_v4_providers (
    provider_id INTEGER PRIMARY KEY,
    provider_key TEXT NOT NULL UNIQUE,
    registration_order INTEGER NOT NULL UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    priority INTEGER NOT NULL DEFAULT 0,
    schema_revision INTEGER NOT NULL,
    metadata_table TEXT NOT NULL,
    applicability_json TEXT NOT NULL,
    declared INTEGER NOT NULL DEFAULT 1 CHECK (declared IN (0, 1))
);

CREATE TABLE IF NOT EXISTS cache_v4_acquisition_groups (
    acquisition_group_id INTEGER PRIMARY KEY,
    provider_id INTEGER NOT NULL REFERENCES cache_v4_providers (provider_id),
    group_key TEXT NOT NULL,
    registration_order INTEGER NOT NULL,
    declared INTEGER NOT NULL DEFAULT 1 CHECK (declared IN (0, 1)),
    UNIQUE (provider_id, group_key),
    UNIQUE (provider_id, registration_order)
);

CREATE TABLE IF NOT EXISTS cache_v4_fields (
    field_id INTEGER PRIMARY KEY,
    provider_id INTEGER NOT NULL REFERENCES cache_v4_providers (provider_id),
    field_name TEXT NOT NULL,
    storage_name TEXT NOT NULL,
    acquisition_group_id INTEGER NOT NULL REFERENCES cache_v4_acquisition_groups (acquisition_group_id),
    registration_order INTEGER NOT NULL,
    type_json TEXT NOT NULL,
    default_freshness_mode TEXT NOT NULL,
    default_max_age_seconds INTEGER,
    priority_override INTEGER,
    freshness_mode_override TEXT,
    max_age_seconds_override INTEGER,
    declared INTEGER NOT NULL DEFAULT 1 CHECK (declared IN (0, 1)),
    UNIQUE (provider_id, field_name),
    UNIQUE (provider_id, storage_name),
    UNIQUE (provider_id, registration_order)
);
