SELECT
    a.outcome,
    a.last_attempt_at,
    a.last_success_at
FROM cache_v4_acquisition_state AS a
INNER JOIN cache_v4_media_entities AS e
    ON a.entity_id = e.entity_id
INNER JOIN cache_v4_providers AS p
    ON a.provider_id = p.provider_id
INNER JOIN cache_v4_acquisition_groups AS g
    ON a.acquisition_group_id = g.acquisition_group_id
WHERE
    e.service = 'youtube'
    AND e.external_id = ?
    AND p.provider_key = 'yt-dlp'
    AND g.group_key = 'detailed';
