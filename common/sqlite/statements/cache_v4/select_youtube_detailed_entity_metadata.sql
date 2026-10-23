-- Preserve the provider metadata wildcard's positional result contract.
-- noqa: disable=AM04,ST06
SELECT
    e.entity_id,
    a.last_success_at,
    m.*,
    c.tags_json,
    c.categories_json,
    c.formats_json,
    c.chapters_json,
    c.thumbnails_json
FROM cache_v4_media_entities AS e
INNER JOIN cache_v4_providers AS p
    ON p.provider_key = 'yt-dlp'
INNER JOIN cache_v4_acquisition_groups AS g
    ON p.provider_id = g.provider_id AND g.group_key = 'detailed'
INNER JOIN cache_v4_acquisition_state AS a
    ON
        e.entity_id = a.entity_id
        AND p.provider_id = a.provider_id
        AND g.acquisition_group_id = a.acquisition_group_id
        AND a.last_success_at IS NOT NULL
LEFT JOIN cache_v4_ytdlp_metadata AS m
    ON e.entity_id = m.entity_id
LEFT JOIN cache_v4_ytdlp_collections AS c
    ON e.entity_id = c.entity_id
WHERE e.service = 'youtube' AND e.external_id = ?;
