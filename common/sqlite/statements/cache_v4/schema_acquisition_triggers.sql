CREATE TRIGGER IF NOT EXISTS cache_v4_acquisition_state_provider_insert
BEFORE INSERT ON cache_v4_acquisition_state
WHEN
    NOT EXISTS (
        SELECT
            1
        FROM cache_v4_acquisition_groups AS g
        WHERE
            g.acquisition_group_id = new.acquisition_group_id
            AND g.provider_id = new.provider_id
    )
BEGIN
    SELECT
        RAISE(ABORT, 'acquisition group does not belong to provider');
END;

CREATE TRIGGER IF NOT EXISTS cache_v4_acquisition_state_provider_update
BEFORE UPDATE OF provider_id, acquisition_group_id ON cache_v4_acquisition_state
WHEN
    NOT EXISTS (
        SELECT
            1
        FROM cache_v4_acquisition_groups AS g
        WHERE
            g.acquisition_group_id = new.acquisition_group_id
            AND g.provider_id = new.provider_id
    )
BEGIN
    SELECT
        RAISE(ABORT, 'acquisition group does not belong to provider');
END;
