CREATE TABLE outbox (
                        outbox_id          BIGINT       NOT NULL AUTO_INCREMENT,
                        command_type       VARCHAR(40)  NOT NULL,
                        aggregate_id       VARCHAR(100) NOT NULL,
                        revision           INT          NOT NULL,
                        idempotency_key    VARCHAR(200) NOT NULL,
                        endpoint_path      VARCHAR(100) NOT NULL,
                        payload            TEXT         NOT NULL,
                        status             VARCHAR(20)  NOT NULL,
                        attempts           INT          NOT NULL,
                        next_attempt_at    DATETIME(6)  NOT NULL,
                        deadline_at        DATETIME(6)  NULL,
                        application_result VARCHAR(20)  NULL,
                        last_error         TEXT         NULL,
                        created_at         DATETIME(6)  NOT NULL,
                        updated_at         DATETIME(6)  NOT NULL,
                        PRIMARY KEY (outbox_id),
                        CONSTRAINT uk_outbox_idem UNIQUE (idempotency_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX idx_outbox_dispatch ON outbox (status, next_attempt_at);