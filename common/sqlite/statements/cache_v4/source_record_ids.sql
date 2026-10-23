SELECT e.external_id FROM cache_v4_sources AS s
INNER JOIN cache_v4_source_entries AS se ON s.source_id = se.source_id
INNER JOIN cache_v4_media_entities AS e ON se.entity_id = e.entity_id
WHERE s.source_url = ? AND s.facet = ''
ORDER BY se.source_index;
