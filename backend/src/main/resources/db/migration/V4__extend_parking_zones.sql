-- zone_type ENUM에 AISLE, ENTRY_EXIT 추가
ALTER TABLE parking_zones
    MODIFY COLUMN zone_type ENUM (
        'DISABLED',
        'EV_CHARGING',
        'GENERAL',
        'AISLE',
        'ENTRY_EXIT'
        ) NULL;

-- HW 매핑 ID + 입출구 역할 컬럼
ALTER TABLE parking_zones
    ADD COLUMN hw_zone_id INT NULL,
    ADD COLUMN entry_exit_role ENUM ('ENTRY', 'EXIT') NULL,
    ADD CONSTRAINT uk_parking_zones_hw_zone_id UNIQUE (hw_zone_id);