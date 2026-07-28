CREATE TABLE users
(
    user_id         BIGINT       NOT NULL AUTO_INCREMENT,
    created_at      DATETIME(6)  NOT NULL,
    updated_at      DATETIME(6)  NOT NULL,
    login_id        VARCHAR(50)  NOT NULL,
    password_hash   VARCHAR(255) NOT NULL,
    phone_number    VARCHAR(20)  NOT NULL,
    building_number VARCHAR(20)  NOT NULL,
    unit_number     VARCHAR(20)  NOT NULL,
    name            VARCHAR(50)  NOT NULL,
    role            ENUM ('ADMIN', 'RESIDENT') NOT NULL,
    status          ENUM ('ACTIVE', 'DELETED', 'PENDING', 'REJECTED', 'SUSPENDED') NOT NULL,

    CONSTRAINT pk_users PRIMARY KEY (user_id),
    CONSTRAINT uk_users_login_id UNIQUE (login_id)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4;


CREATE TABLE user_consents
(
    consent_id      BIGINT      NOT NULL AUTO_INCREMENT,
    created_at      DATETIME(6) NOT NULL,
    user_id         BIGINT      NOT NULL,
    consent_type    ENUM ('PRIVACY_POLICY', 'TERMS_OF_SERVICE') NOT NULL,
    consent_version VARCHAR(20) NOT NULL,
    agreed_at       DATETIME(6) NOT NULL,

    CONSTRAINT pk_user_consents PRIMARY KEY (consent_id),
    CONSTRAINT uk_user_consents_user_type_version
        UNIQUE (user_id, consent_type, consent_version),
    CONSTRAINT fk_user_consents_user
        FOREIGN KEY (user_id) REFERENCES users (user_id)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4;


CREATE TABLE vehicles
(
    vehicle_id         BIGINT      NOT NULL AUTO_INCREMENT,
    created_at         DATETIME(6) NOT NULL,
    updated_at         DATETIME(6) NOT NULL,
    user_id            BIGINT      NOT NULL,
    plate_number       VARCHAR(20) NOT NULL,
    vehicle_model      VARCHAR(50) NULL,
    is_disabled_vehicle BIT(1)     NOT NULL,
    is_electric        BIT(1)      NOT NULL,
    owner_type         ENUM ('RESIDENT', 'VISITOR') NOT NULL,
    visit_date         DATE        NULL,
    status             ENUM ('ACTIVE', 'DELETED', 'PENDING') NOT NULL,

    CONSTRAINT pk_vehicles PRIMARY KEY (vehicle_id),
    CONSTRAINT uk_vehicles_plate_number UNIQUE (plate_number),
    CONSTRAINT fk_vehicles_user
        FOREIGN KEY (user_id) REFERENCES users (user_id)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4;


CREATE TABLE parking_zones
(
    zone_id         BIGINT      NOT NULL AUTO_INCREMENT,
    created_at      DATETIME(6) NOT NULL,
    updated_at      DATETIME(6) NOT NULL,
    zone_number     VARCHAR(20) NOT NULL,
    zone_type       ENUM ('DISABLED', 'EV_CHARGING', 'GENERAL') NULL,
    floor           VARCHAR(20) NULL,
    geometry_data   TEXT        NULL,
    allowed_minutes INT         NULL,
    status          ENUM ('ACTIVE', 'INACTIVE') NULL,

    CONSTRAINT pk_parking_zones PRIMARY KEY (zone_id),
    CONSTRAINT uk_parking_zones_zone_number UNIQUE (zone_number)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4;


CREATE TABLE parking_sessions
(
    session_id              BIGINT       NOT NULL AUTO_INCREMENT,
    created_at              DATETIME(6)  NOT NULL,
    updated_at              DATETIME(6)  NOT NULL,
    vehicle_id              BIGINT       NOT NULL,
    zone_id                 BIGINT       NULL,
    recognized_plate_number VARCHAR(20)  NOT NULL,
    tracking_id             VARCHAR(100) NULL,
    entry_time              DATETIME(6)  NOT NULL,
    parked_at               DATETIME(6)  NULL,
    exit_time               DATETIME(6)  NULL,

    CONSTRAINT pk_parking_sessions PRIMARY KEY (session_id),
    CONSTRAINT fk_parking_sessions_vehicle
        FOREIGN KEY (vehicle_id) REFERENCES vehicles (vehicle_id),
    CONSTRAINT fk_parking_sessions_zone
        FOREIGN KEY (zone_id) REFERENCES parking_zones (zone_id)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4;


CREATE TABLE parking_events
(
    event_id        BIGINT      NOT NULL AUTO_INCREMENT,
    created_at      DATETIME(6) NOT NULL,
    updated_at      DATETIME(6) NOT NULL,
    session_id      BIGINT      NOT NULL,
    vehicle_id      BIGINT      NOT NULL,
    zone_id         BIGINT      NULL,
    event_type      ENUM (
        'BAD_PARKING',
        'DISABLED_ZONE_VIOLATION',
        'DOUBLE_PARKING',
        'EV_OVERSTAY',
        'OUT_OF_ZONE'
        ) NOT NULL,
    reason           TEXT NULL,
    violation_ratio  INT NULL,
    event_status     ENUM (
        'DETECTED',
        'DISMISSED',
        'NEED_ADMIN',
        'REQUESTED',
        'RESOLVED'
        ) NOT NULL,
    detected_at      DATETIME(6) NOT NULL,
    resolved_at      DATETIME(6) NULL,

    CONSTRAINT pk_parking_events PRIMARY KEY (event_id),
    CONSTRAINT fk_parking_events_session
        FOREIGN KEY (session_id) REFERENCES parking_sessions (session_id),
    CONSTRAINT fk_parking_events_vehicle
        FOREIGN KEY (vehicle_id) REFERENCES vehicles (vehicle_id),
    CONSTRAINT fk_parking_events_zone
        FOREIGN KEY (zone_id) REFERENCES parking_zones (zone_id)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4;


CREATE TABLE event_images
(
    image_id    BIGINT       NOT NULL AUTO_INCREMENT,
    created_at  DATETIME(6)  NOT NULL,
    event_id    BIGINT       NOT NULL,
    image_url   VARCHAR(500) NOT NULL,
    image_type  ENUM ('PARKING_STATE', 'PLATE', 'REPORT') NOT NULL,
    captured_at DATETIME(6)  NULL,

    CONSTRAINT pk_event_images PRIMARY KEY (image_id),
    CONSTRAINT fk_event_images_event
        FOREIGN KEY (event_id) REFERENCES parking_events (event_id)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4;


CREATE TABLE move_requests
(
    request_id        BIGINT      NOT NULL AUTO_INCREMENT,
    created_at        DATETIME(6) NOT NULL,
    updated_at        DATETIME(6) NOT NULL,
    event_id          BIGINT      NOT NULL,
    requester_user_id BIGINT      NULL,
    target_vehicle_id BIGINT      NOT NULL,
    request_type      ENUM ('AUTO', 'MANUAL') NOT NULL,
    request_status    ENUM (
        'CANCELLED',
        'COMPLETED',
        'NEED_ADMIN',
        'REMINDER_SENT',
        'RESPONDED',
        'SENT'
        ) NOT NULL,
    message            TEXT       NULL,
    requested_at       DATETIME(6) NOT NULL,
    due_at              DATETIME(6) NULL,
    reminder_count      INT         NOT NULL,

    CONSTRAINT pk_move_requests PRIMARY KEY (request_id),
    CONSTRAINT fk_move_requests_event
        FOREIGN KEY (event_id) REFERENCES parking_events (event_id),
    CONSTRAINT fk_move_requests_requester
        FOREIGN KEY (requester_user_id) REFERENCES users (user_id),
    CONSTRAINT fk_move_requests_target_vehicle
        FOREIGN KEY (target_vehicle_id) REFERENCES vehicles (vehicle_id)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4;


CREATE TABLE move_request_responses
(
    response_id       BIGINT      NOT NULL AUTO_INCREMENT,
    created_at        DATETIME(6) NOT NULL,
    request_id        BIGINT      NOT NULL,
    responder_user_id BIGINT      NOT NULL,
    response_type     ENUM ('CANNOT_MOVE_NOW', 'WILL_MOVE') NOT NULL,
    estimated_minutes INT         NULL,
    responded_at      DATETIME(6) NOT NULL,

    CONSTRAINT pk_move_request_responses PRIMARY KEY (response_id),
    CONSTRAINT fk_move_request_responses_request
        FOREIGN KEY (request_id) REFERENCES move_requests (request_id),
    CONSTRAINT fk_move_request_responses_responder
        FOREIGN KEY (responder_user_id) REFERENCES users (user_id)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4;


CREATE TABLE notifications
(
    notification_id   BIGINT       NOT NULL AUTO_INCREMENT,
    created_at        DATETIME(6)  NOT NULL,
    user_id           BIGINT       NOT NULL,
    event_id          BIGINT       NULL,
    request_id        BIGINT       NULL,
    notification_type ENUM (
        'EVENT_RESOLVED',
        'EV_OVERSTAY',
        'MOVE_REQUEST',
        'REMINDER'
        ) NOT NULL,
    title              VARCHAR(100) NOT NULL,
    body               TEXT         NOT NULL,
    sent_at            DATETIME(6)  NOT NULL,

    CONSTRAINT pk_notifications PRIMARY KEY (notification_id),
    CONSTRAINT fk_notifications_user
        FOREIGN KEY (user_id) REFERENCES users (user_id),
    CONSTRAINT fk_notifications_event
        FOREIGN KEY (event_id) REFERENCES parking_events (event_id),
    CONSTRAINT fk_notifications_request
        FOREIGN KEY (request_id) REFERENCES move_requests (request_id)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4;


CREATE TABLE admin_action_logs
(
    action_log_id BIGINT      NOT NULL AUTO_INCREMENT,
    created_at    DATETIME(6) NOT NULL,
    admin_user_id BIGINT      NOT NULL,
    event_id      BIGINT      NOT NULL,
    action_type   VARCHAR(40) NOT NULL,
    before_status ENUM (
        'DETECTED',
        'DISMISSED',
        'NEED_ADMIN',
        'REQUESTED',
        'RESOLVED'
        ) NULL,
    after_status  ENUM (
        'DETECTED',
        'DISMISSED',
        'NEED_ADMIN',
        'REQUESTED',
        'RESOLVED'
        ) NULL,
    memo          TEXT NULL,

    CONSTRAINT pk_admin_action_logs PRIMARY KEY (action_log_id),
    CONSTRAINT fk_admin_action_logs_admin_user
        FOREIGN KEY (admin_user_id) REFERENCES users (user_id),
    CONSTRAINT fk_admin_action_logs_event
        FOREIGN KEY (event_id) REFERENCES parking_events (event_id)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4;