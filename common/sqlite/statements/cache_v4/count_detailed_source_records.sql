SELECT
    COUNT(*)
FROM cache_v4_sources AS s
INNER JOIN cache_v4_source_entries AS se ON s.source_id = se.source_id
INNER JOIN cache_v4_acquisition_state AS a ON se.entity_id = a.entity_id
INNER JOIN cache_v4_providers AS p ON a.provider_id = p.provider_id
INNER JOIN cache_v4_acquisition_groups AS g ON a.acquisition_group_id = g.acquisition_group_id
WHERE
    s.source_url = ? AND s.facet = '' AND p.provider_key = 'yt-dlp'
    AND g.group_key = 'detailed' AND a.last_success_at IS NOT NULL;
