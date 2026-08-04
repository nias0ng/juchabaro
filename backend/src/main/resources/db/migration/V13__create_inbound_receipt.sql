CREATE TABLE inbound_receipt (
                                 inbound_receipt_id BIGINT       NOT NULL AUTO_INCREMENT,
                                 endpoint           VARCHAR(40)  NOT NULL,
                                 idempotency_key    VARCHAR(100) NOT NULL,
                                 payload_hash       VARCHAR(64)  NOT NULL,
                                 created_at         DATETIME(6)  NOT NULL,
                                 updated_at         DATETIME(6)  NOT NULL,
                                 PRIMARY KEY (inbound_receipt_id),
                                 CONSTRAINT uk_inbound_receipt UNIQUE (endpoint, idempotency_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;