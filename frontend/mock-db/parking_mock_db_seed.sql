-- Parking mock DB: deterministic reset + seed
-- MySQL 8.4 / schema: parking
--
-- 실행 전제
--   1. users에는 admin, resident1, resident2, test1, test2 계정이 ACTIVE 상태로 존재한다.
--   2. parking_zones에는 B1~B3의 93개 구역이 존재한다.
--   3. viewer 계정에서도 실행할 수 있도록 TRUNCATE/ALTER/임시 테이블을 사용하지 않는다.
--
-- 실행 결과
--   - users, parking_zones는 보존한다.
--   - 그 외 테스트/런타임 데이터는 모두 지우고 동일한 목 상태를 다시 만든다.
--   - 차량 41대(test1 23대, test2 18대)
--   - 현재 주차 39대(B1 16대, B2 15대, B3 8대)
--   - 현재 사건/이동 요청 5건(AUTO 3건, MANUAL 2건)
--   - 최근 14일 관리자 조회용 과거 사건 14건(완료 7건, 확인 필요 7건)
--   - 현재 이동 요청 알림 5건, 기본 알림 설정 5건, 관리자 완료 이력 7건
--
-- 주의
--   - device_tokens는 기기별 런타임 값이므로 비운다. 앱 로그인 후 토큰을 다시 등록한다.
--   - event_images는 '등록된 이미지가 없습니다' 빈 상태 테스트를 위해 비운다.
--   - DELETE 방식이라 AUTO_INCREMENT 카운터 자체는 낮아지지 않을 수 있다.
--     시드 레코드는 ID를 명시하므로 결과 ID는 항상 동일하다.

USE parking;
SET NAMES utf8mb4;

SET @old_foreign_key_checks := @@FOREIGN_KEY_CHECKS;
SET @old_sql_safe_updates := @@SQL_SAFE_UPDATES;
SET FOREIGN_KEY_CHECKS = 0;
SET SQL_SAFE_UPDATES = 0;

SET @seed_now := NOW(6);
SET @admin_user_id := (SELECT user_id FROM users WHERE login_id = 'admin' AND status = 'ACTIVE' LIMIT 1);
SET @resident1_user_id := (SELECT user_id FROM users WHERE login_id = 'resident1' AND status = 'ACTIVE' LIMIT 1);
SET @resident2_user_id := (SELECT user_id FROM users WHERE login_id = 'resident2' AND status = 'ACTIVE' LIMIT 1);
SET @test1_user_id := (SELECT user_id FROM users WHERE login_id = 'test1' AND status = 'ACTIVE' LIMIT 1);
SET @test2_user_id := (SELECT user_id FROM users WHERE login_id = 'test2' AND status = 'ACTIVE' LIMIT 1);

-- 실행 전제 확인: required_user_count=5, parking_zone_count=93이어야 한다.
SELECT
    (SELECT COUNT(*) FROM users
      WHERE login_id IN ('admin', 'resident1', 'resident2', 'test1', 'test2')
        AND status = 'ACTIVE') AS required_user_count,
    (SELECT COUNT(*) FROM parking_zones) AS parking_zone_count;

START TRANSACTION;

-- ---------------------------------------------------------------------------
-- 1. 기존 업무/테스트 데이터 정리
-- ---------------------------------------------------------------------------
DELETE FROM admin_action_logs;
DELETE FROM device_tokens;
DELETE FROM entry_decision;
DELETE FROM event_images;
DELETE FROM inbound_receipt;
DELETE FROM outbox;
DELETE FROM move_request_responses;
DELETE FROM notifications;
DELETE FROM move_requests;
DELETE FROM parking_events;
DELETE FROM parking_sessions;
DELETE FROM user_consents;
DELETE FROM user_notification_settings;
DELETE FROM vehicles;

-- ---------------------------------------------------------------------------
-- 2. 기본 알림 설정
-- ---------------------------------------------------------------------------
INSERT INTO user_notification_settings (
    setting_id, created_at, updated_at, user_id,
    move_request_receive, response_reminder, ev_overstay, office_notice,
    quiet_hours_start, quiet_hours_end, channel
)
VALUES
(1, @seed_now, @seed_now, @admin_user_id,     b'1', b'1', b'1', b'0', '23:00:00', '07:00:00', 'PUSH'),
(2, @seed_now, @seed_now, @resident1_user_id, b'1', b'1', b'1', b'0', '23:00:00', '07:00:00', 'PUSH'),
(3, @seed_now, @seed_now, @resident2_user_id, b'1', b'1', b'1', b'0', '23:00:00', '07:00:00', 'PUSH'),
(4, @seed_now, @seed_now, @test1_user_id,     b'1', b'1', b'1', b'0', '23:00:00', '07:00:00', 'PUSH'),
(5, @seed_now, @seed_now, @test2_user_id,     b'1', b'1', b'1', b'0', '23:00:00', '07:00:00', 'PUSH');

-- ---------------------------------------------------------------------------
-- 3. 차량 41대
-- ---------------------------------------------------------------------------
INSERT INTO vehicles (
    vehicle_id, created_at, updated_at, user_id, plate_number, vehicle_model,
    is_disabled_vehicle, is_electric, owner_type, visit_date, status
)
VALUES
-- test1: 23대 / 장애인 5대 / 전기차 7대
(1,  @seed_now, @seed_now, @test1_user_id, '12가7328', '페라리',                    b'1', b'1', 'RESIDENT', NULL, 'ACTIVE'),
(2,  @seed_now, @seed_now, @test1_user_id, '21가1101', '현대 아반떼',              b'0', b'0', 'RESIDENT', NULL, 'ACTIVE'),
(3,  @seed_now, @seed_now, @test1_user_id, '22나1102', '기아 쏘렌토',              b'0', b'0', 'RESIDENT', NULL, 'ACTIVE'),
(4,  @seed_now, @seed_now, @test1_user_id, '23다1103', '현대 쏘나타',              b'0', b'0', 'RESIDENT', NULL, 'ACTIVE'),
(5,  @seed_now, @seed_now, @test1_user_id, '24라1104', '기아 K5',                  b'0', b'0', 'RESIDENT', NULL, 'ACTIVE'),
(6,  @seed_now, @seed_now, @test1_user_id, '25마1105', '제네시스 GV70',            b'0', b'0', 'RESIDENT', NULL, 'ACTIVE'),
(7,  @seed_now, @seed_now, @test1_user_id, '26거1106', '테슬라 모델 3',            b'0', b'1', 'RESIDENT', NULL, 'ACTIVE'),
(8,  @seed_now, @seed_now, @test1_user_id, '27너1107', '현대 아이오닉 5',          b'0', b'1', 'RESIDENT', NULL, 'ACTIVE'),
(9,  @seed_now, @seed_now, @test1_user_id, '28더1108', '기아 EV6',                 b'0', b'1', 'RESIDENT', NULL, 'ACTIVE'),
(10, @seed_now, @seed_now, @test1_user_id, '29러1109', '현대 코나 일렉트릭',       b'0', b'1', 'RESIDENT', NULL, 'ACTIVE'),
(11, @seed_now, @seed_now, @test1_user_id, '30머1110', '기아 니로 EV',             b'0', b'1', 'RESIDENT', NULL, 'ACTIVE'),
(12, @seed_now, @seed_now, @test1_user_id, '31버1111', '기아 카니발',              b'1', b'0', 'RESIDENT', NULL, 'ACTIVE'),
(13, @seed_now, @seed_now, @test1_user_id, '32서1112', '현대 싼타페',              b'1', b'0', 'RESIDENT', NULL, 'ACTIVE'),
(14, @seed_now, @seed_now, @test1_user_id, '33어1113', '기아 니로 EV 장애인 차량', b'1', b'1', 'RESIDENT', NULL, 'ACTIVE'),
(15, @seed_now, @seed_now, @test1_user_id, '34저1114', '현대 투싼',                b'0', b'0', 'RESIDENT', NULL, 'ACTIVE'),
(16, @seed_now, @seed_now, @test1_user_id, '35고1115', '기아 레이',                b'0', b'0', 'RESIDENT', NULL, 'ACTIVE'),
(17, @seed_now, @seed_now, @test1_user_id, '61가2001', '현대 아반떼',              b'0', b'0', 'RESIDENT', NULL, 'ACTIVE'),
(18, @seed_now, @seed_now, @test1_user_id, '62나2002', '기아 K5',                  b'0', b'0', 'RESIDENT', NULL, 'ACTIVE'),
(19, @seed_now, @seed_now, @test1_user_id, '63다2003', '현대 투싼',                b'0', b'0', 'RESIDENT', NULL, 'ACTIVE'),
(38, @seed_now, @seed_now, @test1_user_id, '72거3001', '현대 아반떼',              b'0', b'0', 'RESIDENT', NULL, 'ACTIVE'),
(39, @seed_now, @seed_now, @test1_user_id, '73너3002', '기아 K8',                  b'0', b'0', 'RESIDENT', NULL, 'ACTIVE'),
(40, @seed_now, @seed_now, @test1_user_id, '74더3003', '현대 스타리아 장애인 차량', b'1', b'0', 'RESIDENT', NULL, 'ACTIVE'),
(41, @seed_now, @seed_now, @test1_user_id, '75러3004', '르노 그랑 콜레오스',       b'0', b'0', 'RESIDENT', NULL, 'ACTIVE'),

-- test2: 18대 / 장애인 3대 / 전기차 6대
(20, @seed_now, @seed_now, @test2_user_id, '98라5678', '벤츠',                     b'0', b'0', 'RESIDENT', NULL, 'ACTIVE'),
(21, @seed_now, @seed_now, @test2_user_id, '41가1201', '현대 그랜저',              b'0', b'0', 'RESIDENT', NULL, 'ACTIVE'),
(22, @seed_now, @seed_now, @test2_user_id, '42나1202', '기아 스포티지',            b'0', b'0', 'RESIDENT', NULL, 'ACTIVE'),
(23, @seed_now, @seed_now, @test2_user_id, '43다1203', '현대 팰리세이드',          b'0', b'0', 'RESIDENT', NULL, 'ACTIVE'),
(24, @seed_now, @seed_now, @test2_user_id, '44라1204', '기아 셀토스',              b'0', b'0', 'RESIDENT', NULL, 'ACTIVE'),
(25, @seed_now, @seed_now, @test2_user_id, '45마1205', '제네시스 G80',             b'0', b'0', 'RESIDENT', NULL, 'ACTIVE'),
(26, @seed_now, @seed_now, @test2_user_id, '46거1206', '테슬라 모델 Y',            b'0', b'1', 'RESIDENT', NULL, 'ACTIVE'),
(27, @seed_now, @seed_now, @test2_user_id, '47너1207', '현대 아이오닉 6',          b'0', b'1', 'RESIDENT', NULL, 'ACTIVE'),
(28, @seed_now, @seed_now, @test2_user_id, '48더1208', '기아 EV9',                 b'0', b'1', 'RESIDENT', NULL, 'ACTIVE'),
(29, @seed_now, @seed_now, @test2_user_id, '49러1209', '제네시스 GV60',            b'0', b'1', 'RESIDENT', NULL, 'ACTIVE'),
(30, @seed_now, @seed_now, @test2_user_id, '50머1210', 'BMW i4',                   b'0', b'1', 'RESIDENT', NULL, 'ACTIVE'),
(31, @seed_now, @seed_now, @test2_user_id, '51버1211', '현대 스타리아',            b'1', b'0', 'RESIDENT', NULL, 'ACTIVE'),
(32, @seed_now, @seed_now, @test2_user_id, '52서1212', '기아 카니발',              b'1', b'0', 'RESIDENT', NULL, 'ACTIVE'),
(33, @seed_now, @seed_now, @test2_user_id, '53어1213', '현대 아이오닉 5 장애인 차량', b'1', b'1', 'RESIDENT', NULL, 'ACTIVE'),
(34, @seed_now, @seed_now, @test2_user_id, '54저1214', '르노 아르카나',            b'0', b'0', 'RESIDENT', NULL, 'ACTIVE'),
(35, @seed_now, @seed_now, @test2_user_id, '55고1215', '쉐보레 트래버스',          b'0', b'0', 'RESIDENT', NULL, 'ACTIVE'),
(36, @seed_now, @seed_now, @test2_user_id, '64라2004', '기아 스포티지',            b'0', b'0', 'RESIDENT', NULL, 'ACTIVE'),
(37, @seed_now, @seed_now, @test2_user_id, '65마2005', '제네시스 G70',             b'0', b'0', 'RESIDENT', NULL, 'ACTIVE');

-- ---------------------------------------------------------------------------
-- 4. 현재 주차 세션 39건
--    미주차 차량: 22나1102(vehicle_id=3), 75러3004(vehicle_id=41)
-- ---------------------------------------------------------------------------
INSERT INTO parking_sessions (
    session_id, created_at, updated_at, vehicle_id, zone_id,
    recognized_plate_number, entry_attempt_id, entry_time, parked_at,
    exit_time, idempotency_key, context_revision
)
SELECT
    p.session_id,
    DATE_SUB(@seed_now, INTERVAL (p.parked_minutes_ago + 5) MINUTE),
    @seed_now,
    v.vehicle_id,
    z.zone_id,
    v.plate_number,
    CONCAT('mock-entry-', LPAD(p.session_id, 2, '0')),
    DATE_SUB(@seed_now, INTERVAL (p.parked_minutes_ago + 5) MINUTE),
    DATE_SUB(@seed_now, INTERVAL p.parked_minutes_ago MINUTE),
    NULL,
    CONCAT('mock-parking-session-', LPAD(p.session_id, 2, '0')),
    0
FROM (
    SELECT 1 AS session_id, '63다2003' AS plate_number, 'B2-24' AS zone_number, 55 AS parked_minutes_ago
    UNION ALL SELECT 2,  '41가1201', 'B1-14',      115
    UNION ALL SELECT 3,  '98라5678', 'B3-24',       45
    UNION ALL SELECT 5,  '55고1215', 'D3-01',      500
    UNION ALL SELECT 6,  '50머1210', 'B1-22',      255
    UNION ALL SELECT 7,  '25마1105', 'D2-01',      610
    UNION ALL SELECT 8,  '61가2001', 'B1-09',       85
    UNION ALL SELECT 9,  '34저1114', 'AISLE3-01',  155
    UNION ALL SELECT 10, '12가7328', 'B2-13',      730
    UNION ALL SELECT 11, '48더1208', 'AISLE2-01',   95
    UNION ALL SELECT 12, '44라1204', 'B1-07',      190
    UNION ALL SELECT 13, '53어1213', 'EV3-01',     960
    UNION ALL SELECT 14, '28더1108', 'EV1-02',     310
    UNION ALL SELECT 15, '42나1202', 'B2-23',      260
    UNION ALL SELECT 16, '52서1212', 'B2-10',      515
    UNION ALL SELECT 17, '27너1107', 'B3-23',      305
    UNION ALL SELECT 18, '24라1104', 'B1-23',      145
    UNION ALL SELECT 19, '32서1112', 'B2-01',      730
    UNION ALL SELECT 20, '64라2004', 'B1-16',      680
    UNION ALL SELECT 21, '46거1206', 'B3-02',      180
    UNION ALL SELECT 22, '31버1111', 'B1-08',      340
    UNION ALL SELECT 23, '45마1205', 'B2-02',      120
    UNION ALL SELECT 24, '47너1207', 'B2-21',       60
    UNION ALL SELECT 25, '33어1113', 'B3-01',      690
    UNION ALL SELECT 26, '35고1115', 'B1-24',      275
    UNION ALL SELECT 27, '29러1109', 'B2-03',      380
    UNION ALL SELECT 28, '43다1203', 'B1-12',      900
    UNION ALL SELECT 29, '49러1209', 'B3-04',       80
    UNION ALL SELECT 30, '62나2002', 'B1-17',       35
    UNION ALL SELECT 31, '51버1211', 'B2-04',      215
    UNION ALL SELECT 32, '21가1101', 'B2-06',      485
    UNION ALL SELECT 33, '26거1106', 'EV2-02',     420
    UNION ALL SELECT 34, '54저1214', 'B1-19',      205
    UNION ALL SELECT 35, '23다1103', 'B2-07',      640
    UNION ALL SELECT 36, '30머1110', 'B1-15',      775
    UNION ALL SELECT 37, '65마2005', 'B2-16',       75
    UNION ALL SELECT 38, '72거3001', 'B1-21',      130
    UNION ALL SELECT 39, '73너3002', 'B1-10',       70
    UNION ALL SELECT 40, '74더3003', 'B1-04',      240
) p
JOIN vehicles v ON v.plate_number = p.plate_number AND v.status = 'ACTIVE'
JOIN parking_zones z ON TRIM(z.zone_number) = p.zone_number AND z.status = 'ACTIVE';

-- ---------------------------------------------------------------------------
-- 5. 현재 위반 사건 5건
-- ---------------------------------------------------------------------------
INSERT INTO parking_events (
    event_id, created_at, updated_at, session_id, vehicle_id, zone_id,
    event_type, reason, violation_ratio, event_status, detected_at, resolved_at,
    incident_id, publication_revision, rule_code, physical_vehicle_id, entry_attempt_id
)
SELECT
    e.event_id,
    CASE WHEN e.event_type = 'EV_OVERSTAY'
         THEN DATE_ADD(ps.parked_at, INTERVAL COALESCE(z.allowed_minutes, 840) MINUTE)
         ELSE DATE_ADD(ps.parked_at, INTERVAL e.detected_after_minutes MINUTE) END,
    @seed_now,
    ps.session_id,
    v.vehicle_id,
    z.zone_id,
    e.event_type,
    e.reason,
    e.violation_ratio,
    'REQUESTED',
    CASE WHEN e.event_type = 'EV_OVERSTAY'
         THEN DATE_ADD(ps.parked_at, INTERVAL COALESCE(z.allowed_minutes, 840) MINUTE)
         ELSE DATE_ADD(ps.parked_at, INTERVAL e.detected_after_minutes MINUTE) END,
    NULL,
    e.incident_id,
    1,
    e.rule_code,
    NULL,
    ps.entry_attempt_id
FROM (
    SELECT 1 AS event_id, '25마1105' AS plate_number, 'D2-01' AS zone_number,
           'DISABLED_ZONE_VIOLATION' AS event_type,
           '장애인 전용구역에 비장애인 차량이 주차되어 있습니다.' AS reason,
           96 AS violation_ratio, 10 AS detected_after_minutes,
           'DISABLED_ZONE_UNAUTHORIZED' AS rule_code,
           '00000000-0000-0000-0000-000000000001' AS incident_id
    UNION ALL SELECT 2, '48더1208', 'AISLE2-01', 'DOUBLE_PARKING',
           '통로에 이중주차된 차량이 신고되었습니다.', 91, 15,
           'DOUBLE_PARKING', '00000000-0000-0000-0000-000000000002'
    UNION ALL SELECT 3, '55고1215', 'D3-01', 'DISABLED_ZONE_VIOLATION',
           '장애인 전용구역에 비장애인 차량이 주차되어 있습니다.', 94, 10,
           'DISABLED_ZONE_UNAUTHORIZED', '00000000-0000-0000-0000-000000000003'
    UNION ALL SELECT 4, '34저1114', 'AISLE3-01', 'DOUBLE_PARKING',
           '통로에 이중주차된 차량이 신고되었습니다.', 89, 15,
           'DOUBLE_PARKING', '00000000-0000-0000-0000-000000000004'
    UNION ALL SELECT 5, '53어1213', 'EV3-01', 'EV_OVERSTAY',
           '전기차 충전 구역의 허용 시간을 초과했습니다.', 100, 840,
           'EV_OVERSTAY', '00000000-0000-0000-0000-000000000005'
) e
JOIN vehicles v ON v.plate_number = e.plate_number AND v.status = 'ACTIVE'
JOIN parking_sessions ps ON ps.vehicle_id = v.vehicle_id AND ps.exit_time IS NULL
JOIN parking_zones z ON z.zone_id = ps.zone_id AND TRIM(z.zone_number) = e.zone_number;

-- ---------------------------------------------------------------------------
-- 6. 현재 이동 요청 5건
--    요청 시간은 매 실행 시 NOW() 기준 5~21분 전으로 재설정한다.
--    따라서 실행 직후 스케줄러가 재알림/관리자 확인으로 바꾸지 않는다.
-- ---------------------------------------------------------------------------
INSERT INTO move_requests (
    request_id, created_at, updated_at, event_id, requester_user_id,
    target_vehicle_id, request_type, request_status, message, requested_at,
    due_at, reminder_count, reminder_sent_at, verification_attempt
)
SELECT
    r.request_id,
    DATE_SUB(@seed_now, INTERVAL r.minutes_ago MINUTE),
    DATE_SUB(@seed_now, INTERVAL r.minutes_ago MINUTE),
    pe.event_id,
    requester.user_id,
    pe.vehicle_id,
    r.request_type,
    'SENT',
    r.message,
    DATE_SUB(@seed_now, INTERVAL r.minutes_ago MINUTE),
    NULL,
    0,
    NULL,
    0
FROM (
    SELECT 1 AS request_id, 1 AS event_id, 'AUTO' AS request_type, NULL AS requester_login_id,
           '장애인 전용구역 위반이 감지되어 자동으로 차량 이동을 요청합니다.' AS message, 5 AS minutes_ago
    UNION ALL SELECT 2, 2, 'MANUAL', 'test1',
           '통로 이중주차로 통행이 어려우니 차량을 이동해 주세요.', 9
    UNION ALL SELECT 3, 3, 'AUTO', NULL,
           '장애인 전용구역 위반이 감지되어 자동으로 차량 이동을 요청합니다.', 13
    UNION ALL SELECT 4, 4, 'MANUAL', 'test2',
           '통로 이중주차로 통행이 어려우니 차량을 이동해 주세요.', 17
    UNION ALL SELECT 5, 5, 'AUTO', NULL,
           '전기차 충전 구역의 허용 시간을 초과하여 자동으로 차량 이동을 요청합니다.', 21
) r
JOIN parking_events pe ON pe.event_id = r.event_id
LEFT JOIN users requester
       ON requester.login_id = r.requester_login_id AND requester.status = 'ACTIVE';

-- 현재 요청의 인앱 알림. 푸시 전송 기록이 아니라 알림함/상세 테스트용 데이터다.
INSERT INTO notifications (
    notification_id, created_at, user_id, event_id, request_id,
    notification_type, title, body, sent_at
)
SELECT
    n.notification_id,
    mr.requested_at,
    owner.user_id,
    pe.event_id,
    mr.request_id,
    n.notification_type,
    n.title,
    n.body,
    mr.requested_at
FROM (
    SELECT 1 AS notification_id, 1 AS request_id, 'MOVE_REQUEST' AS notification_type,
           '차량 이동 요청' AS title,
           '장애인 전용구역 주차가 감지되었습니다. 차량 이동을 부탁드립니다.' AS body
    UNION ALL SELECT 2, 2, 'MOVE_REQUEST', '차량 이동 요청',
           '등록하신 차량에 이동 요청이 접수되었습니다.'
    UNION ALL SELECT 3, 3, 'MOVE_REQUEST', '차량 이동 요청',
           '장애인 전용구역 주차가 감지되었습니다. 차량 이동을 부탁드립니다.'
    UNION ALL SELECT 4, 4, 'MOVE_REQUEST', '차량 이동 요청',
           '등록하신 차량에 이동 요청이 접수되었습니다.'
    UNION ALL SELECT 5, 5, 'EV_OVERSTAY', '전기차 충전구역 초과',
           '충전구역 허용 시간을 초과했습니다. 차량 이동을 부탁드립니다.'
) n
JOIN move_requests mr ON mr.request_id = n.request_id
JOIN parking_events pe ON pe.event_id = mr.event_id
JOIN vehicles v ON v.vehicle_id = mr.target_vehicle_id
JOIN users owner ON owner.user_id = v.user_id;

-- ---------------------------------------------------------------------------
-- 7. 최근 14일 관리자 목록용 과거 세션/사건/요청 14건
--    고정 날짜 대신 실행일 기준 1~13일 전을 사용한다.
-- ---------------------------------------------------------------------------
INSERT INTO parking_sessions (
    session_id, created_at, updated_at, vehicle_id, zone_id,
    recognized_plate_number, entry_attempt_id, entry_time, parked_at,
    exit_time, idempotency_key, context_revision
)
SELECT
    h.session_id,
    DATE_SUB(h.event_at, INTERVAL 60 MINUTE),
    DATE_ADD(h.event_at, INTERVAL 45 MINUTE),
    v.vehicle_id,
    z.zone_id,
    v.plate_number,
    CONCAT('mock-history-entry-', h.session_id),
    DATE_SUB(h.event_at, INTERVAL 60 MINUTE),
    DATE_SUB(h.event_at, INTERVAL 55 MINUTE),
    DATE_ADD(h.event_at, INTERVAL 45 MINUTE),
    CONCAT('mock-history-session-', h.session_id),
    0
FROM (
    SELECT 42 AS session_id, '22나1102' AS plate_number, 'B2-18' AS zone_number,
           TIMESTAMP(DATE_SUB(DATE(@seed_now), INTERVAL 13 DAY), '09:20:00') AS event_at
    UNION ALL SELECT 43, '23다1103', 'AISLE3-01', TIMESTAMP(DATE_SUB(DATE(@seed_now), INTERVAL 12 DAY), '18:10:00')
    UNION ALL SELECT 44, '24라1104', 'D2-02',     TIMESTAMP(DATE_SUB(DATE(@seed_now), INTERVAL 11 DAY), '11:35:00')
    UNION ALL SELECT 45, '26거1106', 'EV2-01',    TIMESTAMP(DATE_SUB(DATE(@seed_now), INTERVAL 10 DAY), '16:45:00')
    UNION ALL SELECT 46, '27너1107', 'AISLE2-01', TIMESTAMP(DATE_SUB(DATE(@seed_now), INTERVAL 9 DAY),  '20:05:00')
    UNION ALL SELECT 47, '34저1114', 'B3-19',     TIMESTAMP(DATE_SUB(DATE(@seed_now), INTERVAL 8 DAY),  '08:40:00')
    UNION ALL SELECT 48, '35고1115', 'D3-02',     TIMESTAMP(DATE_SUB(DATE(@seed_now), INTERVAL 7 DAY),  '14:25:00')
    UNION ALL SELECT 49, '61가2001', 'AISLE3-01', TIMESTAMP(DATE_SUB(DATE(@seed_now), INTERVAL 6 DAY),  '19:15:00')
    UNION ALL SELECT 50, '41가1201', 'B1-13',     TIMESTAMP(DATE_SUB(DATE(@seed_now), INTERVAL 5 DAY),  '10:30:00')
    UNION ALL SELECT 51, '42나1202', 'AISLE2-01', TIMESTAMP(DATE_SUB(DATE(@seed_now), INTERVAL 4 DAY),  '07:50:00')
    UNION ALL SELECT 52, '43다1203', 'B2-22',     TIMESTAMP(DATE_SUB(DATE(@seed_now), INTERVAL 4 DAY),  '21:10:00')
    UNION ALL SELECT 53, '44라1204', 'AISLE2-01', TIMESTAMP(DATE_SUB(DATE(@seed_now), INTERVAL 3 DAY),  '13:45:00')
    UNION ALL SELECT 54, '45마1205', 'D2-02',     TIMESTAMP(DATE_SUB(DATE(@seed_now), INTERVAL 2 DAY),  '17:20:00')
    UNION ALL SELECT 55, '49러1209', 'EV2-01',    TIMESTAMP(DATE_SUB(DATE(@seed_now), INTERVAL 1 DAY),  '09:05:00')
) h
JOIN vehicles v ON v.plate_number = h.plate_number AND v.status = 'ACTIVE'
JOIN parking_zones z ON TRIM(z.zone_number) = h.zone_number AND z.status = 'ACTIVE';

INSERT INTO parking_events (
    event_id, created_at, updated_at, session_id, vehicle_id, zone_id,
    event_type, reason, violation_ratio, event_status, detected_at, resolved_at,
    incident_id, publication_revision, rule_code, physical_vehicle_id, entry_attempt_id
)
SELECT
    e.event_id,
    e.detected_at,
    CASE WHEN e.event_status = 'RESOLVED'
         THEN DATE_ADD(e.detected_at, INTERVAL 30 MINUTE)
         ELSE DATE_ADD(e.detected_at, INTERVAL 121 MINUTE) END,
    ps.session_id,
    ps.vehicle_id,
    ps.zone_id,
    e.event_type,
    e.reason,
    e.violation_ratio,
    e.event_status,
    e.detected_at,
    CASE WHEN e.event_status = 'RESOLVED'
         THEN DATE_ADD(e.detected_at, INTERVAL 30 MINUTE) ELSE NULL END,
    e.incident_id,
    1,
    e.rule_code,
    NULL,
    ps.entry_attempt_id
FROM (
    SELECT 6 AS event_id, 42 AS session_id,
           TIMESTAMP(DATE_SUB(DATE(@seed_now), INTERVAL 13 DAY), '09:20:00') AS detected_at,
           'BAD_PARKING' AS event_type, '주차선 침범이 감지되었습니다.' AS reason,
           82 AS violation_ratio, 'RESOLVED' AS event_status, 'BAD_PARKING' AS rule_code,
           '10000000-0000-0000-0000-000000000006' AS incident_id
    UNION ALL SELECT 7, 43, TIMESTAMP(DATE_SUB(DATE(@seed_now), INTERVAL 12 DAY), '18:10:00'),
           'DOUBLE_PARKING', '통로 이중주차 신고가 접수되었습니다.', 90, 'RESOLVED', 'DOUBLE_PARKING', '10000000-0000-0000-0000-000000000007'
    UNION ALL SELECT 8, 44, TIMESTAMP(DATE_SUB(DATE(@seed_now), INTERVAL 11 DAY), '11:35:00'),
           'DISABLED_ZONE_VIOLATION', '장애인 전용구역 위반이 감지되었습니다.', 95, 'RESOLVED', 'DISABLED_ZONE_UNAUTHORIZED', '10000000-0000-0000-0000-000000000008'
    UNION ALL SELECT 9, 45, TIMESTAMP(DATE_SUB(DATE(@seed_now), INTERVAL 10 DAY), '16:45:00'),
           'EV_OVERSTAY', '전기차 충전 허용 시간을 초과했습니다.', 100, 'RESOLVED', 'EV_OVERSTAY', '10000000-0000-0000-0000-000000000009'
    UNION ALL SELECT 10, 46, TIMESTAMP(DATE_SUB(DATE(@seed_now), INTERVAL 9 DAY), '20:05:00'),
           'DOUBLE_PARKING', '통로 이중주차 신고가 접수되었습니다.', 88, 'RESOLVED', 'DOUBLE_PARKING', '10000000-0000-0000-0000-000000000010'
    UNION ALL SELECT 11, 47, TIMESTAMP(DATE_SUB(DATE(@seed_now), INTERVAL 8 DAY), '08:40:00'),
           'OUT_OF_ZONE', '지정 구역을 벗어난 주차가 감지되었습니다.', 84, 'RESOLVED', 'OUT_OF_ZONE', '10000000-0000-0000-0000-000000000011'
    UNION ALL SELECT 12, 48, TIMESTAMP(DATE_SUB(DATE(@seed_now), INTERVAL 7 DAY), '14:25:00'),
           'DISABLED_ZONE_VIOLATION', '장애인 전용구역 위반이 감지되었습니다.', 97, 'RESOLVED', 'DISABLED_ZONE_UNAUTHORIZED', '10000000-0000-0000-0000-000000000012'
    UNION ALL SELECT 13, 49, TIMESTAMP(DATE_SUB(DATE(@seed_now), INTERVAL 6 DAY), '19:15:00'),
           'DOUBLE_PARKING', '통로 이중주차 신고가 접수되었습니다.', 92, 'NEED_ADMIN', 'DOUBLE_PARKING', '10000000-0000-0000-0000-000000000013'
    UNION ALL SELECT 14, 50, TIMESTAMP(DATE_SUB(DATE(@seed_now), INTERVAL 5 DAY), '10:30:00'),
           'BAD_PARKING', '주차선 침범이 반복 감지되었습니다.', 87, 'NEED_ADMIN', 'BAD_PARKING', '10000000-0000-0000-0000-000000000014'
    UNION ALL SELECT 15, 51, TIMESTAMP(DATE_SUB(DATE(@seed_now), INTERVAL 4 DAY), '07:50:00'),
           'DOUBLE_PARKING', '통로 이중주차 신고가 접수되었습니다.', 89, 'NEED_ADMIN', 'DOUBLE_PARKING', '10000000-0000-0000-0000-000000000015'
    UNION ALL SELECT 16, 52, TIMESTAMP(DATE_SUB(DATE(@seed_now), INTERVAL 4 DAY), '21:10:00'),
           'BAD_PARKING', '주차선 침범이 감지되었습니다.', 80, 'NEED_ADMIN', 'BAD_PARKING', '10000000-0000-0000-0000-000000000016'
    UNION ALL SELECT 17, 53, TIMESTAMP(DATE_SUB(DATE(@seed_now), INTERVAL 3 DAY), '13:45:00'),
           'OUT_OF_ZONE', '지정 구역을 벗어난 주차가 감지되었습니다.', 86, 'NEED_ADMIN', 'OUT_OF_ZONE', '10000000-0000-0000-0000-000000000017'
    UNION ALL SELECT 18, 54, TIMESTAMP(DATE_SUB(DATE(@seed_now), INTERVAL 2 DAY), '17:20:00'),
           'DISABLED_ZONE_VIOLATION', '장애인 전용구역 위반이 감지되었습니다.', 96, 'NEED_ADMIN', 'DISABLED_ZONE_UNAUTHORIZED', '10000000-0000-0000-0000-000000000018'
    UNION ALL SELECT 19, 55, TIMESTAMP(DATE_SUB(DATE(@seed_now), INTERVAL 1 DAY), '09:05:00'),
           'EV_OVERSTAY', '전기차 충전 허용 시간을 초과했습니다.', 100, 'NEED_ADMIN', 'EV_OVERSTAY', '10000000-0000-0000-0000-000000000019'
) e
JOIN parking_sessions ps ON ps.session_id = e.session_id;

INSERT INTO move_requests (
    request_id, created_at, updated_at, event_id, requester_user_id,
    target_vehicle_id, request_type, request_status, message, requested_at,
    due_at, reminder_count, reminder_sent_at, verification_attempt
)
SELECT
    r.request_id,
    DATE_ADD(pe.detected_at, INTERVAL 1 MINUTE),
    CASE WHEN r.request_status = 'COMPLETED' THEN pe.resolved_at
         ELSE DATE_ADD(pe.detected_at, INTERVAL 121 MINUTE) END,
    pe.event_id,
    requester.user_id,
    pe.vehicle_id,
    r.request_type,
    r.request_status,
    r.message,
    DATE_ADD(pe.detected_at, INTERVAL 1 MINUTE),
    NULL,
    CASE WHEN r.request_status = 'NEED_ADMIN' THEN 1 ELSE 0 END,
    CASE WHEN r.request_status = 'NEED_ADMIN'
         THEN DATE_ADD(pe.detected_at, INTERVAL 61 MINUTE) ELSE NULL END,
    CASE WHEN r.request_status = 'NEED_ADMIN' THEN 1 ELSE 0 END
FROM (
    SELECT 6 AS request_id, 6 AS event_id, 'AUTO' AS request_type, NULL AS requester_login_id,
           'COMPLETED' AS request_status, '주차 위반이 감지되어 자동 이동 요청을 전송했습니다.' AS message
    UNION ALL SELECT 7, 7, 'MANUAL', 'test2', 'COMPLETED', '통로 이중주차 차량에 수동 이동 요청을 전송했습니다.'
    UNION ALL SELECT 8, 8, 'AUTO', NULL, 'COMPLETED', '장애인 전용구역 위반으로 자동 이동 요청을 전송했습니다.'
    UNION ALL SELECT 9, 9, 'AUTO', NULL, 'COMPLETED', '전기차 충전 시간 초과로 자동 이동 요청을 전송했습니다.'
    UNION ALL SELECT 10, 10, 'MANUAL', 'test2', 'COMPLETED', '통로 이중주차 차량에 수동 이동 요청을 전송했습니다.'
    UNION ALL SELECT 11, 11, 'AUTO', NULL, 'COMPLETED', '구역 외 주차가 감지되어 자동 이동 요청을 전송했습니다.'
    UNION ALL SELECT 12, 12, 'AUTO', NULL, 'COMPLETED', '장애인 전용구역 위반으로 자동 이동 요청을 전송했습니다.'
    UNION ALL SELECT 13, 13, 'MANUAL', 'test2', 'NEED_ADMIN', '통로 이중주차 차량에 수동 이동 요청을 전송했습니다.'
    UNION ALL SELECT 14, 14, 'AUTO', NULL, 'NEED_ADMIN', '주차선 침범이 감지되어 자동 이동 요청을 전송했습니다.'
    UNION ALL SELECT 15, 15, 'MANUAL', 'test1', 'NEED_ADMIN', '통로 이중주차 차량에 수동 이동 요청을 전송했습니다.'
    UNION ALL SELECT 16, 16, 'AUTO', NULL, 'NEED_ADMIN', '주차선 침범이 감지되어 자동 이동 요청을 전송했습니다.'
    UNION ALL SELECT 17, 17, 'AUTO', NULL, 'NEED_ADMIN', '구역 외 주차가 감지되어 자동 이동 요청을 전송했습니다.'
    UNION ALL SELECT 18, 18, 'AUTO', NULL, 'NEED_ADMIN', '장애인 전용구역 위반으로 자동 이동 요청을 전송했습니다.'
    UNION ALL SELECT 19, 19, 'AUTO', NULL, 'NEED_ADMIN', '전기차 충전 시간 초과로 자동 이동 요청을 전송했습니다.'
) r
JOIN parking_events pe ON pe.event_id = r.event_id
LEFT JOIN users requester
       ON requester.login_id = r.requester_login_id AND requester.status = 'ACTIVE';

-- 완료 사건 7건의 관리자 조치 이력
INSERT INTO admin_action_logs (
    action_log_id, created_at, admin_user_id, event_id,
    action_type, before_status, after_status, memo
)
SELECT
    pe.event_id - 5,
    pe.resolved_at,
    @admin_user_id,
    pe.event_id,
    'COMPLETE',
    'REQUESTED',
    'RESOLVED',
    '목 데이터: 관리자 조치 완료'
FROM parking_events pe
WHERE pe.event_id BETWEEN 6 AND 12
  AND pe.event_status = 'RESOLVED';

COMMIT;

SET FOREIGN_KEY_CHECKS = @old_foreign_key_checks;
SET SQL_SAFE_UPDATES = @old_sql_safe_updates;

-- ---------------------------------------------------------------------------
-- 8. 최종 검증: 모든 validation_result가 PASS여야 한다.
-- ---------------------------------------------------------------------------
SELECT 'required_users' AS validation_name,
       IF(COUNT(*) = 5, 'PASS', 'FAIL') AS validation_result,
       CONCAT(COUNT(*), ' / 5') AS actual_expected
FROM users
WHERE login_id IN ('admin', 'resident1', 'resident2', 'test1', 'test2')
  AND status = 'ACTIVE'
UNION ALL
SELECT 'parking_zones', IF(COUNT(*) = 93, 'PASS', 'FAIL'), CONCAT(COUNT(*), ' / 93')
FROM parking_zones
UNION ALL
SELECT 'vehicles', IF(COUNT(*) = 41, 'PASS', 'FAIL'), CONCAT(COUNT(*), ' / 41')
FROM vehicles
UNION ALL
SELECT 'active_sessions', IF(COUNT(*) = 39, 'PASS', 'FAIL'), CONCAT(COUNT(*), ' / 39')
FROM parking_sessions WHERE exit_time IS NULL
UNION ALL
SELECT 'current_events', IF(COUNT(*) = 5, 'PASS', 'FAIL'), CONCAT(COUNT(*), ' / 5')
FROM parking_events WHERE event_id BETWEEN 1 AND 5
UNION ALL
SELECT 'historical_events', IF(COUNT(*) = 14, 'PASS', 'FAIL'), CONCAT(COUNT(*), ' / 14')
FROM parking_events WHERE event_id BETWEEN 6 AND 19
UNION ALL
SELECT 'move_requests', IF(COUNT(*) = 19, 'PASS', 'FAIL'), CONCAT(COUNT(*), ' / 19')
FROM move_requests
UNION ALL
SELECT 'notifications', IF(COUNT(*) = 5, 'PASS', 'FAIL'), CONCAT(COUNT(*), ' / 5')
FROM notifications
UNION ALL
SELECT 'notification_settings', IF(COUNT(*) = 5, 'PASS', 'FAIL'), CONCAT(COUNT(*), ' / 5')
FROM user_notification_settings
UNION ALL
SELECT 'admin_action_logs', IF(COUNT(*) = 7, 'PASS', 'FAIL'), CONCAT(COUNT(*), ' / 7')
FROM admin_action_logs;

-- 층별 현재 주차: B1=16, B2=15, B3=8
SELECT z.floor, COUNT(*) AS parked_vehicle_count
FROM parking_sessions ps
JOIN parking_zones z ON z.zone_id = ps.zone_id
WHERE ps.exit_time IS NULL
GROUP BY z.floor
ORDER BY z.floor;

-- 반드시 0이어야 하는 B1 빈 구역
SELECT COUNT(*) AS forbidden_b1_occupied_count
FROM parking_sessions ps
JOIN parking_zones z ON z.zone_id = ps.zone_id
WHERE ps.exit_time IS NULL
  AND TRIM(z.zone_number) IN ('EV1-01', 'B1-02', 'B1-03', 'B1-05', 'B1-01', 'D1-01');

-- 차량 소유/특성 요약
SELECT
    u.login_id,
    COUNT(*) AS total_vehicles,
    SUM(v.is_disabled_vehicle = b'1') AS disabled_vehicles,
    SUM(v.is_electric = b'1') AS electric_vehicles,
    SUM(ps.session_id IS NOT NULL) AS currently_parked
FROM vehicles v
JOIN users u ON u.user_id = v.user_id
LEFT JOIN parking_sessions ps ON ps.vehicle_id = v.vehicle_id AND ps.exit_time IS NULL
GROUP BY u.login_id
ORDER BY u.login_id;

-- 현재 요청 상태: AUTO 3 / MANUAL 2, 모두 SENT
SELECT mr.request_type, mr.request_status, COUNT(*) AS request_count
FROM move_requests mr
WHERE mr.request_id BETWEEN 1 AND 5
GROUP BY mr.request_type, mr.request_status
ORDER BY mr.request_type;

-- 관리자 과거 사건: RESOLVED 7 / NEED_ADMIN 7
SELECT pe.event_status, COUNT(*) AS event_count
FROM parking_events pe
WHERE pe.event_id BETWEEN 6 AND 19
GROUP BY pe.event_status
ORDER BY pe.event_status;
