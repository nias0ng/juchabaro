CREATE TABLE device_tokens (
                               device_token_id BIGINT       NOT NULL AUTO_INCREMENT,
                               user_id         BIGINT       NOT NULL,
                               token           VARCHAR(512) NOT NULL,
                               platform        VARCHAR(20)  NULL,
                               created_at      DATETIME(6)  NOT NULL,
                               updated_at      DATETIME(6)  NOT NULL,
                               PRIMARY KEY (device_token_id),
                               CONSTRAINT uk_device_tokens_token UNIQUE (token),
                               CONSTRAINT fk_device_tokens_user FOREIGN KEY (user_id) REFERENCES users (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;