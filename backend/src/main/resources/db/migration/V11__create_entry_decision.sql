CREATE TABLE entry_decision (
                                entry_decision_id BIGINT       NOT NULL AUTO_INCREMENT,
                                idempotency_key   VARCHAR(100) NOT NULL,
                                entry_attempt_id  VARCHAR(100) NOT NULL,
                                payload_hash      VARCHAR(64)  NOT NULL,
                                access_decision   VARCHAR(10)  NOT NULL,
                                decision_revision INT          NOT NULL,
                                vehicle_id        BIGINT       NULL,
                                session_id        BIGINT       NULL,
                                created_at        DATETIME(6)  NOT NULL,
                                updated_at        DATETIME(6)  NOT NULL,
                                PRIMARY KEY (entry_decision_id),
                                CONSTRAINT uk_entry_decision_idem UNIQUE (idempotency_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;