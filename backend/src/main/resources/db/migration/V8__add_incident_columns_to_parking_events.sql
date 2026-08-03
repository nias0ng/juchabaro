ALTER TABLE parking_events
    ADD COLUMN incident_id          VARCHAR(36)  NULL,
    ADD COLUMN publication_revision INT          NULL,
    ADD COLUMN rule_code            VARCHAR(40)  NULL,
    ADD COLUMN physical_vehicle_id  VARCHAR(36)  NULL,
    ADD COLUMN entry_attempt_id     VARCHAR(100) NULL,
    ADD CONSTRAINT uk_parking_events_incident_id UNIQUE (incident_id);