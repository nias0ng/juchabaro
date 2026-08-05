-- baro-web/admin-web 사건 목록용 더미 데이터
-- 대상: MySQL 8.0+
-- 생성 건수: 2026-07-31 70건 / 08-01 83건 / 08-02 51건 / 08-03 88건 / 08-04 91건 (총 383건)
--
-- 이 스크립트는 실제 DB에 자동 적용되지 않습니다. 사용할 DB를 선택한 뒤 직접 실행하세요.
-- 사건 ID는 parking_events.event_id(AUTO_INCREMENT)가 자동 생성합니다.
-- 같은 스크립트를 다시 실행해도 incident_id 기준으로 사건이 중복 생성되지 않습니다.

START TRANSACTION;

DROP TEMPORARY TABLE IF EXISTS tmp_dummy_numbers;
CREATE TEMPORARY TABLE tmp_dummy_numbers (n INT NOT NULL PRIMARY KEY);

INSERT INTO tmp_dummy_numbers (n)
WITH RECURSIVE seq AS (
    SELECT 1
    UNION ALL
    SELECT n + 1 FROM seq WHERE n < 91
)
SELECT n FROM seq;

DROP TEMPORARY TABLE IF EXISTS tmp_admin_events;
CREATE TEMPORARY TABLE tmp_admin_events AS
SELECT
    d.event_date,
    n.n AS daily_no,
    CONCAT('dummy-admin-', DATE_FORMAT(d.event_date, '%Y%m%d'), '-', LPAD(n.n, 3, '0')) AS dummy_key,
    TIMESTAMP(d.event_date, '06:00:00')
        + INTERVAL MOD(n.n * 613, 64800) SECOND AS detected_at,
    CONCAT(
        CASE MOD(n.n - 1, 4)
            WHEN 0 THEN '12가'
            WHEN 1 THEN '34나'
            WHEN 2 THEN '56다'
            ELSE '78라'
        END,
        LPAD(MOD(DAYOFYEAR(d.event_date) * 97 + n.n * 37, 10000), 4, '0')
    ) AS plate_number,
    CONCAT(
        CASE MOD(n.n - 1, 3) WHEN 0 THEN 'B1' WHEN 1 THEN 'B2' ELSE 'B3' END,
        '-', LPAD(MOD(n.n - 1, 30) + 1, 2, '0')
    ) AS zone_number,
    CASE MOD(n.n - 1, 6)
        WHEN 0 THEN 'BAD_PARKING'
        WHEN 1 THEN 'DOUBLE_PARKING'
        WHEN 2 THEN 'DISABLED_ZONE_VIOLATION'
        WHEN 3 THEN 'EV_OVERSTAY'
        WHEN 4 THEN 'OUT_OF_ZONE'
        ELSE 'ETC'
    END AS event_type,
    72 + MOD(n.n * 11 + DAY(d.event_date), 28) AS violation_ratio,
    CASE MOD(n.n - 1, 5)
        WHEN 0 THEN 'DETECTED'
        WHEN 1 THEN 'REQUESTED'
        WHEN 2 THEN 'NEED_ADMIN'
        WHEN 3 THEN 'RESOLVED'
        ELSE 'DISMISSED'
    END AS event_status
FROM (
    SELECT DATE('2026-07-31') AS event_date, 70 AS event_count
    UNION ALL SELECT DATE('2026-08-01'), 83
    UNION ALL SELECT DATE('2026-08-02'), 51
    UNION ALL SELECT DATE('2026-08-03'), 88
    UNION ALL SELECT DATE('2026-08-04'), 91
) d
JOIN tmp_dummy_numbers n ON n.n <= d.event_count;

ALTER TABLE tmp_admin_events
    ADD PRIMARY KEY (dummy_key),
    ADD INDEX idx_tmp_plate (plate_number),
    ADD INDEX idx_tmp_zone (zone_number);

-- 차량 외래키를 위한 더미 사용자 1명
INSERT INTO users (
    created_at, updated_at, login_id, password_hash, phone_number,
    building_number, unit_number, name, role, status
)
SELECT
    NOW(6), NOW(6), 'dummy_admin_event_owner',
    '{noop}dummy-not-for-login', '010-0000-0000',
    'DUMMY', '0000', '사건목록 더미 소유자', 'RESIDENT', 'ACTIVE'
WHERE NOT EXISTS (
    SELECT 1 FROM users WHERE login_id = 'dummy_admin_event_owner'
);

SET @dummy_user_id := (
    SELECT user_id FROM users WHERE login_id = 'dummy_admin_event_owner' LIMIT 1
);

-- 화면의 차량 번호에 표시될 차량
INSERT INTO vehicles (
    created_at, updated_at, user_id, plate_number, vehicle_model,
    is_disabled_vehicle, is_electric, owner_type, visit_date, status
)
SELECT DISTINCT
    NOW(6), NOW(6), @dummy_user_id, t.plate_number, '더미 차량',
    IF(t.event_type = 'DISABLED_ZONE_VIOLATION', b'0', b'1'),
    IF(t.event_type = 'EV_OVERSTAY', b'1', b'0'),
    'RESIDENT', NULL, 'ACTIVE'
FROM tmp_admin_events t
WHERE NOT EXISTS (
    SELECT 1 FROM vehicles v WHERE v.plate_number = t.plate_number
);

-- 화면의 위치에 표시될 주차 구역 90개(B1~B3, 층별 30개)
INSERT INTO parking_zones (
    created_at, updated_at, zone_number, zone_type, floor,
    geometry_data, allowed_minutes, status
)
SELECT
    NOW(6), NOW(6), t.zone_number,
    CASE MOD(CAST(SUBSTRING_INDEX(t.zone_number, '-', -1) AS UNSIGNED), 10)
        WHEN 1 THEN 'DISABLED'
        WHEN 2 THEN 'EV_CHARGING'
        ELSE 'GENERAL'
    END,
    SUBSTRING_INDEX(t.zone_number, '-', 1), NULL, 120, 'ACTIVE'
FROM tmp_admin_events t
WHERE NOT EXISTS (
    SELECT 1 FROM parking_zones z WHERE z.zone_number = t.zone_number
)
GROUP BY t.zone_number;

-- 사건이 참조할 주차 세션(더미 키로 재실행 중복 방지)
INSERT INTO parking_sessions (
    created_at, updated_at, vehicle_id, zone_id, recognized_plate_number,
    entry_attempt_id, entry_time, parked_at, exit_time, idempotency_key
)
SELECT
    t.detected_at - INTERVAL 35 MINUTE,
    t.detected_at,
    v.vehicle_id,
    z.zone_id,
    t.plate_number,
    CONCAT('entry-', t.dummy_key),
    t.detected_at - INTERVAL 35 MINUTE,
    t.detected_at - INTERVAL 25 MINUTE,
    CASE WHEN t.event_status IN ('RESOLVED', 'DISMISSED')
         THEN t.detected_at + INTERVAL (10 + MOD(t.daily_no, 50)) MINUTE
         ELSE NULL END,
    CONCAT('session-', t.dummy_key)
FROM tmp_admin_events t
JOIN vehicles v ON v.plate_number = t.plate_number
JOIN parking_zones z ON z.zone_number = t.zone_number
WHERE NOT EXISTS (
    SELECT 1 FROM parking_sessions ps
    WHERE ps.idempotency_key = CONCAT('session-', t.dummy_key)
);

-- 사건 목록 본문: ID/차량번호/유형/위치/발생시간/AI 신뢰도/상태
INSERT INTO parking_events (
    created_at, updated_at, session_id, vehicle_id, zone_id,
    event_type, reason, violation_ratio, event_status,
    detected_at, resolved_at, incident_id, publication_revision,
    rule_code, physical_vehicle_id, entry_attempt_id
)
SELECT
    t.detected_at,
    CASE WHEN t.event_status IN ('RESOLVED', 'DISMISSED')
         THEN t.detected_at + INTERVAL (10 + MOD(t.daily_no, 50)) MINUTE
         ELSE t.detected_at END,
    ps.session_id,
    v.vehicle_id,
    z.zone_id,
    t.event_type,
    CONCAT('관리자 사건 목록 테스트용 더미 데이터 (', t.dummy_key, ')'),
    t.violation_ratio,
    t.event_status,
    t.detected_at,
    CASE WHEN t.event_status = 'RESOLVED'
         THEN t.detected_at + INTERVAL (10 + MOD(t.daily_no, 50)) MINUTE
         ELSE NULL END,
    t.dummy_key,
    1,
    CASE t.event_type
        WHEN 'DISABLED_ZONE_VIOLATION' THEN 'DISABLED_ZONE_UNAUTHORIZED'
        ELSE t.event_type
    END,
    CONCAT('dummy-vehicle-', LPAD(v.vehicle_id, 10, '0')),
    CONCAT('entry-', t.dummy_key)
FROM tmp_admin_events t
JOIN vehicles v ON v.plate_number = t.plate_number
JOIN parking_zones z ON z.zone_number = t.zone_number
JOIN parking_sessions ps ON ps.idempotency_key = CONCAT('session-', t.dummy_key)
WHERE NOT EXISTS (
    SELECT 1 FROM parking_events pe WHERE pe.incident_id = t.dummy_key
);

-- 조치 열의 '재알림' 활성화에 필요한 이동 요청.
-- REQUESTED/NEED_ADMIN 사건에 생성하며, 상세 보기 버튼은 모든 사건에 기본 노출됩니다.
INSERT INTO move_requests (
    created_at, updated_at, event_id, requester_user_id, target_vehicle_id,
    request_type, request_status, message, requested_at, due_at,
    reminder_count, reminder_sent_at
)
SELECT
    pe.detected_at + INTERVAL 1 MINUTE,
    pe.detected_at + INTERVAL 1 MINUTE,
    pe.event_id,
    NULL,
    pe.vehicle_id,
    'AUTO',
    CASE pe.event_status
        WHEN 'NEED_ADMIN' THEN 'NEED_ADMIN'
        ELSE 'SENT'
    END,
    '더미 이동 요청입니다.',
    pe.detected_at + INTERVAL 1 MINUTE,
    CASE WHEN pe.event_status = 'REQUESTED'
         THEN pe.detected_at + INTERVAL 11 MINUTE ELSE NULL END,
    0,
    NULL
FROM parking_events pe
WHERE pe.incident_id LIKE 'dummy-admin-%'
  AND pe.event_status IN ('REQUESTED', 'NEED_ADMIN')
  AND NOT EXISTS (
      SELECT 1 FROM move_requests mr WHERE mr.event_id = pe.event_id
  );

-- 실행 결과 검증: 날짜별 건수가 70, 83, 51, 88, 91인지 확인
SELECT
    DATE(detected_at) AS event_date,
    COUNT(*) AS event_count
FROM parking_events
WHERE incident_id LIKE 'dummy-admin-%'
  AND detected_at >= '2026-07-31 00:00:00'
  AND detected_at <  '2026-08-05 00:00:00'
GROUP BY DATE(detected_at)
ORDER BY event_date;

DROP TEMPORARY TABLE IF EXISTS tmp_admin_events;
DROP TEMPORARY TABLE IF EXISTS tmp_dummy_numbers;

COMMIT;
