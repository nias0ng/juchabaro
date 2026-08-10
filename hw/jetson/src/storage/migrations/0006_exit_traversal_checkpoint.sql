-- Exit traversal is a workflow checkpoint, not a public aggregate or an
-- outbox publication source. One active row per PhysicalVehicle survives the
-- originating ZoneVisit and process restart until exit confirmation consumes
-- it or confirmed re-entry invalidates it.

CREATE TABLE exit_traversal_checkpoints (
    physical_vehicle_id TEXT PRIMARY KEY,
    exit_zone_id INTEGER NOT NULL CHECK (exit_zone_id > 0),
    exit_zone_visit_id TEXT NOT NULL,
    zone_definition_version INTEGER NOT NULL CHECK (
        zone_definition_version >= 1
    ),
    outward_observed_at_us INTEGER NOT NULL,
    reentry_candidate_at_us INTEGER,
    reentry_trusted_duration_us INTEGER NOT NULL DEFAULT 0 CHECK (
        reentry_trusted_duration_us >= 0
    ),
    reentry_confirmation_duration_us INTEGER NOT NULL CHECK (
        reentry_confirmation_duration_us > 0
    ),
    last_trusted_sample_at_us INTEGER,
    record_version INTEGER NOT NULL DEFAULT 1 CHECK (record_version >= 1),
    updated_at_us INTEGER NOT NULL,
    CHECK (
        (reentry_candidate_at_us IS NULL
            AND reentry_trusted_duration_us = 0
            AND last_trusted_sample_at_us IS NULL)
        OR (reentry_candidate_at_us IS NOT NULL
            AND last_trusted_sample_at_us IS NOT NULL
            AND last_trusted_sample_at_us >= reentry_candidate_at_us)
    ),
    CHECK (updated_at_us >= outward_observed_at_us),
    CHECK (
        reentry_candidate_at_us IS NULL
        OR reentry_candidate_at_us >= outward_observed_at_us
    ),
    CHECK (
        last_trusted_sample_at_us IS NULL
        OR (
            last_trusted_sample_at_us >= outward_observed_at_us
            AND updated_at_us >= last_trusted_sample_at_us
        )
    ),
    FOREIGN KEY (physical_vehicle_id)
        REFERENCES physical_vehicles(physical_vehicle_id)
);

CREATE TRIGGER exit_traversal_checkpoint_immutable_origin
BEFORE UPDATE OF
    physical_vehicle_id, exit_zone_id, exit_zone_visit_id,
    zone_definition_version, outward_observed_at_us,
    reentry_confirmation_duration_us
ON exit_traversal_checkpoints
FOR EACH ROW
WHEN
    NEW.physical_vehicle_id <> OLD.physical_vehicle_id
    OR NEW.exit_zone_id <> OLD.exit_zone_id
    OR NEW.exit_zone_visit_id <> OLD.exit_zone_visit_id
    OR NEW.zone_definition_version <> OLD.zone_definition_version
    OR NEW.outward_observed_at_us <> OLD.outward_observed_at_us
    OR NEW.reentry_confirmation_duration_us
        <> OLD.reentry_confirmation_duration_us
BEGIN
    SELECT RAISE(ABORT, 'exit traversal checkpoint origin is immutable');
END;
