SELECT
    p.metadata_table
FROM cache_v4_providers AS p
INNER JOIN sqlite_master AS m
    ON p.metadata_table = m.name AND m.type = 'table';
