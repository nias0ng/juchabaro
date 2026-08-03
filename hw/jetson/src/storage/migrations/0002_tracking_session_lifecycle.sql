-- 0001은 checksum으로 보호되는 immutable migration이다. tracking/session
-- 수명주기 보강은 기존 DB에도 순차 적용할 수 있도록 별도 migration으로 둔다.

ALTER TABLE physical_vehicles
ADD COLUMN trusted_sample_max_gap_duration_us INTEGER;

ALTER TABLE physical_vehicles
ADD COLUMN absence_confirmed_at_us INTEGER;

-- 0001에는 trusted sample gap이 없었다. 아직 외부 배포 전인 기존 local
-- snapshot에는 현재 파일럿 배포값 1초를 한 번만 채운다. 이후 신규 row는
-- repository가 실제 설정 scalar를 명시하며 아래 trigger가 누락을 거부한다.
UPDATE physical_vehicles
SET trusted_sample_max_gap_duration_us = 1000000;

-- 구 schema가 보존한 정보만으로 최초 threshold crossing을 복구할 수는 없다.
-- 이미 threshold에 도달한 legacy checkpoint는 마지막 durable checkpoint
-- 시각을 보수적인 occurredAt 하한으로 사용한다.
UPDATE physical_vehicles
SET absence_confirmed_at_us = updated_at_us
WHERE absence_trusted_duration_us >= absence_confirmation_duration_us;

CREATE TRIGGER trg_physical_vehicle_absence_contract_insert
BEFORE INSERT ON physical_vehicles
WHEN NEW.absence_confirmation_duration_us <= 0
    OR NEW.trusted_sample_max_gap_duration_us IS NULL
    OR NEW.trusted_sample_max_gap_duration_us <= 0
    OR (
        (NEW.absence_trusted_duration_us >= NEW.absence_confirmation_duration_us)
        != (NEW.absence_confirmed_at_us IS NOT NULL)
    )
BEGIN
    SELECT RAISE(ABORT, 'invalid physical vehicle absence snapshot');
END;

CREATE TRIGGER trg_physical_vehicle_absence_contract_update
BEFORE UPDATE ON physical_vehicles
WHEN NEW.absence_confirmation_duration_us <= 0
    OR NEW.trusted_sample_max_gap_duration_us IS NULL
    OR NEW.trusted_sample_max_gap_duration_us <= 0
    OR (
        (NEW.absence_trusted_duration_us >= NEW.absence_confirmation_duration_us)
        != (NEW.absence_confirmed_at_us IS NOT NULL)
    )
BEGIN
    SELECT RAISE(ABORT, 'invalid physical vehicle absence snapshot');
END;

CREATE TRIGGER trg_entry_match_deadline_insert
BEFORE INSERT ON entry_match_attempts
WHEN NEW.match_deadline_at_us IS NULL
BEGIN
    SELECT RAISE(ABORT, 'entry match deadline is required');
END;

CREATE TRIGGER trg_entry_match_deadline_update
BEFORE UPDATE ON entry_match_attempts
WHEN NEW.match_deadline_at_us IS NULL
BEGIN
    SELECT RAISE(ABORT, 'entry match deadline is required');
END;

CREATE TRIGGER trg_session_mirror_presence_identity_insert
BEFORE INSERT ON parking_session_mirrors
WHEN (
        NEW.physical_presence_state = 'UNCONFIRMED'
        AND NEW.physical_vehicle_id IS NOT NULL
    )
    OR (
        NEW.physical_presence_state <> 'UNCONFIRMED'
        AND NEW.physical_vehicle_id IS NULL
    )
BEGIN
    SELECT RAISE(ABORT, 'invalid session mirror presence identity');
END;

CREATE TRIGGER trg_session_mirror_presence_identity_update
BEFORE UPDATE ON parking_session_mirrors
WHEN (
        NEW.physical_presence_state = 'UNCONFIRMED'
        AND NEW.physical_vehicle_id IS NOT NULL
    )
    OR (
        NEW.physical_presence_state <> 'UNCONFIRMED'
        AND NEW.physical_vehicle_id IS NULL
    )
BEGIN
    SELECT RAISE(ABORT, 'invalid session mirror presence identity');
END;

-- 기존 row도 새 invariant를 통과하는지 migration transaction 안에서 확인한다.
UPDATE physical_vehicles SET record_version = record_version;
UPDATE entry_match_attempts SET record_version = record_version;
UPDATE parking_session_mirrors SET record_version = record_version;
