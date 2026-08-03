CREATE TABLE user_notification_settings
(
    setting_id           BIGINT      NOT NULL AUTO_INCREMENT,
    created_at           DATETIME(6) NOT NULL,
    updated_at           DATETIME(6) NOT NULL,
    user_id              BIGINT      NOT NULL,
    move_request_receive BIT(1)      NOT NULL DEFAULT b'1',
    response_reminder    BIT(1)      NOT NULL DEFAULT b'1',
    ev_overstay          BIT(1)      NOT NULL DEFAULT b'1',
    office_notice        BIT(1)      NOT NULL DEFAULT b'0',
    quiet_hours_start    TIME        NOT NULL DEFAULT '23:00:00',
    quiet_hours_end      TIME        NOT NULL DEFAULT '07:00:00',
    channel              ENUM ('PUSH', 'PUSH_SMS') NOT NULL DEFAULT 'PUSH',
    CONSTRAINT pk_user_notification_settings PRIMARY KEY (setting_id),
    CONSTRAINT uk_user_notification_settings_user UNIQUE (user_id),
    CONSTRAINT fk_user_notification_settings_user
        FOREIGN KEY (user_id) REFERENCES users (user_id)
) ENGINE = InnoDB;