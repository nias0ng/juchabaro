ALTER TABLE parking_sessions
    ADD COLUMN idempotency_key VARCHAR(100) NULL;

ALTER TABLE parking_sessions
    ADD CONSTRAINT uk_parking_sessions_idempotency_key UNIQUE (idempotency_key);