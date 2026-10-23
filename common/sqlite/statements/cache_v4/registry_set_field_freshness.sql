UPDATE cache_v4_fields
SET freshness_mode_override = ?, max_age_seconds_override = ?
WHERE field_id = ?
