SELECT
    p.provider_id,
    g.acquisition_group_id
FROM cache_v4_providers AS p
INNER JOIN cache_v4_acquisition_groups AS g ON p.provider_id = g.provider_id
WHERE
    p.provider_key = ? AND p.declared = 1
    AND g.group_key = ? AND g.declared = 1;
