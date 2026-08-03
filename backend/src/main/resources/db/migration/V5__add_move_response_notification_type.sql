ALTER TABLE notifications
    MODIFY COLUMN notification_type ENUM (
        'MOVE_REQUEST',
        'MOVE_RESPONSE',
        'REMINDER',
        'EV_OVERSTAY',
        'EVENT_RESOLVED'
        ) NOT NULL;