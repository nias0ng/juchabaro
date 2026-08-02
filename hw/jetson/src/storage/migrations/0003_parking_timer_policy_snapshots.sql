-- 진행 중 parking aggregate는 생성 당시의 trusted sample 연속성 정책을
-- restart 뒤에도 유지해야 한다. 기존 local DB는 파일럿의 현재 직접 설정값
-- 1초를 보수적인 호환값으로 한 번 채우고, 신규 row는 repository가 실제
-- 적용값을 명시한다.

ALTER TABLE zone_visits
ADD COLUMN trusted_sample_max_gap_duration_us INTEGER;

ALTER TABLE parking_episodes
ADD COLUMN trusted_sample_max_gap_duration_us INTEGER;

ALTER TABLE incidents
ADD COLUMN trusted_sample_max_gap_duration_us INTEGER;

UPDATE zone_visits
SET trusted_sample_max_gap_duration_us = 1000000;

UPDATE parking_episodes
SET trusted_sample_max_gap_duration_us = 1000000;

UPDATE incidents
SET trusted_sample_max_gap_duration_us = 1000000;

CREATE TRIGGER trg_zone_visit_trusted_gap_insert
BEFORE INSERT ON zone_visits
WHEN NEW.trusted_sample_max_gap_duration_us IS NULL
    OR NEW.trusted_sample_max_gap_duration_us <= 0
BEGIN
    SELECT RAISE(ABORT, 'zone visit trusted sample gap is required');
END;

CREATE TRIGGER trg_zone_visit_trusted_gap_update
BEFORE UPDATE ON zone_visits
WHEN NEW.trusted_sample_max_gap_duration_us IS NULL
    OR NEW.trusted_sample_max_gap_duration_us <= 0
BEGIN
    SELECT RAISE(ABORT, 'zone visit trusted sample gap is required');
END;

CREATE TRIGGER trg_parking_episode_trusted_gap_insert
BEFORE INSERT ON parking_episodes
WHEN NEW.trusted_sample_max_gap_duration_us IS NULL
    OR NEW.trusted_sample_max_gap_duration_us <= 0
BEGIN
    SELECT RAISE(ABORT, 'parking episode trusted sample gap is required');
END;

CREATE TRIGGER trg_parking_episode_trusted_gap_update
BEFORE UPDATE ON parking_episodes
WHEN NEW.trusted_sample_max_gap_duration_us IS NULL
    OR NEW.trusted_sample_max_gap_duration_us <= 0
BEGIN
    SELECT RAISE(ABORT, 'parking episode trusted sample gap is required');
END;

CREATE TRIGGER trg_incident_trusted_gap_insert
BEFORE INSERT ON incidents
WHEN NEW.trusted_sample_max_gap_duration_us IS NULL
    OR NEW.trusted_sample_max_gap_duration_us <= 0
BEGIN
    SELECT RAISE(ABORT, 'incident trusted sample gap is required');
END;

CREATE TRIGGER trg_incident_trusted_gap_update
BEFORE UPDATE ON incidents
WHEN NEW.trusted_sample_max_gap_duration_us IS NULL
    OR NEW.trusted_sample_max_gap_duration_us <= 0
BEGIN
    SELECT RAISE(ABORT, 'incident trusted sample gap is required');
END;

-- 기존 row도 새 trigger invariant를 migration transaction 안에서 확인한다.
UPDATE zone_visits SET record_version = record_version;
UPDATE parking_episodes SET record_version = record_version;
UPDATE incidents SET record_version = record_version;
