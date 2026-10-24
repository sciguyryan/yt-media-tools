UPDATE cache_v4_acquisition_state
SET last_attempt_at = ?, last_success_at = ?
WHERE
    entity_id = ?
    AND provider_id = (
        SELECT provider_id
        FROM cache_v4_providers
        WHERE provider_key = 'yt-dlp'
    )
    AND acquisition_group_id = (
        SELECT g.acquisition_group_id
        FROM cache_v4_acquisition_groups AS g
        INNER JOIN cache_v4_providers AS p
            ON g.provider_id = p.provider_id
        WHERE p.provider_key = 'yt-dlp' AND g.group_key = 'detailed'
    );
