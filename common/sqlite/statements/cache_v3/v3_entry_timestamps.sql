-- Preserve the historical validator's positional result-column contract.
-- noqa: disable=ST06
SELECT
    source_url || '/' || video_id AS entry_identity,
    observed_at
FROM source_entries
