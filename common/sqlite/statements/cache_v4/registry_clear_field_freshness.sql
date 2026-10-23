UPDATE cache_v4_fields
SET freshness_mode_override = NULL, max_age_seconds_override = NULL
WHERE field_id = ?
