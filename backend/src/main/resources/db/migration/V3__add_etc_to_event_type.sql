ALTER TABLE parking_events
    MODIFY COLUMN event_type ENUM (
        'BAD_PARKING',
        'DISABLED_ZONE_VIOLATION',
        'DOUBLE_PARKING',
        'EV_OVERSTAY',
        'OUT_OF_ZONE',
        'ETC'
    ) NOT NULL;
