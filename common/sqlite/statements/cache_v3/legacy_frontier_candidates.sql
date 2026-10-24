SELECT
    o.source_url,
    o.source_kind,
    o.last_observed_at,
    o.observed_entries,
    (
        SELECT
            e.video_id
        FROM source_entries AS e
        WHERE e.source_url = o.source_url
        ORDER BY e.source_index
        LIMIT 1
    ) AS first_video_id
FROM source_observations AS o
WHERE
    o.observed_entries > 0
    AND o.observed_entries = (
        SELECT
            COUNT(*)
        FROM source_entries AS e2
        WHERE e2.source_url = o.source_url
    )
