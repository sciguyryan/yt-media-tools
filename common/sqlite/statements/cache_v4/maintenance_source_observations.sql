SELECT
    s.source_id,
    s.source_url,
    s.facet,
    o.last_observed_at
FROM cache_v4_sources AS s
INNER JOIN cache_v4_source_observations AS o ON s.source_id = o.source_id
ORDER BY s.source_id;
