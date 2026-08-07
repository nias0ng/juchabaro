"""테스트 전역 설정.

Settings에 기본값 없는 필수 필드가 있어 .env 없이 get_settings()를 부르면
ValidationError가 난다. 순수 로직 테스트가 환경 파일 존재에 의존하지 않도록
여기서 값을 주입한다. 실제 임계값과 하드웨어 설정은 .env로 주며 이 값은
테스트용이다.

(436 병합) 이 파일에 있던 sys.path 조작은 제거했다. 420이 추가했을 당시에는
`src.` 임포트를 해결할 유일한 수단이었으나, 421의 pyproject.toml이
`pythonpath = ["."]`로 같은 일을 하므로 중복이 됐다.
"""

import pytest

REQUIRED_ENV = {
    "DATABASE_PATH": ":memory:",
    "EVIDENCE_SPOOL_PATH": "data/test-evidence",
    "EVIDENCE_SPOOL_CAP_BYTES": str(8 * 1024 * 1024),
    "ZONE_DEFINITION_PATH": "config/zone_definition.json",
    "EGRESS_AISLE_PATH": "config/egress_aisle.json",
    # 아래 monitoring 값은 Settings 파싱을 위한 테스트 전용 값이다.
    # 운영 임계값을 나타내지 않는다.
    "CAMERA_ID": "TEST-CAMERA",
    "CAMERA_INDEX": "0",
    "CALIBRATION_PATH": "config/test-calibration.json",
    "VEHICLE_MODEL_PATH": "model/test.engine",
    "VEHICLE_MODEL_MANIFEST_PATH": "model/test-manifest.json",
    "VEHICLE_TRACKING_CONFIDENCE": "0.5",
    "ZONE_ENTRY_CONFIRM_SECONDS": "3.0",
    "ZONE_EXIT_CONFIRM_SECONDS": "3.0",
    "EXIT_REENTRY_CONFIRMATION_SECONDS": "1.0",
    "REIDENTIFICATION_MAX_GAP_SECONDS": "4.0",
    "REIDENTIFICATION_MIN_SCORE": "0.42",
    "REIDENTIFICATION_AMBIGUITY_MARGIN": "0.08",
    "INCIDENT_DISABLED_ZONE_UNAUTHORIZED_CONFIRM_SECONDS": "0.0",
    "INCIDENT_DISABLED_ZONE_UNAUTHORIZED_CLEAR_SECONDS": "0.0",
    "INCIDENT_EV_ZONE_UNAUTHORIZED_CONFIRM_SECONDS": "0.0",
    "INCIDENT_EV_ZONE_UNAUTHORIZED_CLEAR_SECONDS": "0.0",
    "INCIDENT_EV_OVERSTAY_CONFIRM_SECONDS": "0.0",
    "INCIDENT_EV_OVERSTAY_CLEAR_SECONDS": "0.0",
    "INCIDENT_BAD_PARKING_CONFIRM_SECONDS": "0.5",
    "INCIDENT_BAD_PARKING_CLEAR_SECONDS": "0.5",
    "INCIDENT_OUT_OF_ZONE_CONFIRM_SECONDS": "0.5",
    "INCIDENT_OUT_OF_ZONE_CLEAR_SECONDS": "0.5",
    "INCIDENT_AISLE_BLOCK_CONFIRM_SECONDS": "0.5",
    "INCIDENT_AISLE_BLOCK_CLEAR_SECONDS": "0.5",
    "INCIDENT_DOUBLE_PARKING_CONFIRM_SECONDS": "0.0",
    "INCIDENT_DOUBLE_PARKING_CLEAR_SECONDS": "0.0",
    "ZONE_PRESENCE_MIN_OVERLAP_RATIO": "0.40",
    "ASSIGNMENT_MIN_OVERLAP_RATIO": "0.50",
    "ASSIGNMENT_AMBIGUOUS_MARGIN": "0.05",
    "BAD_PARKING_MIN_PRIMARY_OVERLAP_RATIO": "0.75",
    "BAD_PARKING_MIN_SECONDARY_OVERLAP_RATIO": "0.25",
    "OUT_OF_ZONE_MIN_SPOT_OVERLAP_RATIO": "0.50",
    "BLOCKING_RELATION_CONFIRM_SECONDS": "1.0",
    "BLOCKING_RELATION_CLEAR_SECONDS": "1.0",
    "BLOCKING_MIN_SUBJECT_OVERLAP_RATIO": "0.40",
    "BLOCKING_MIN_EGRESS_COVERAGE_RATIO": "0.40",
    "ABSENCE_CONFIRMATION_SECONDS": "5.0",
    "TRUSTED_SAMPLE_MAX_GAP_SECONDS": "1.0",
    "MOTION_WINDOW_SECONDS": "0.75",
    "MOTION_MIN_OBSERVATION_SPAN_SECONDS": "0.20",
    "MOTION_MAX_SAMPLE_GAP_SECONDS": "0.50",
    "MOTION_STATIONARY_THRESHOLD": "0.03",
    "MOTION_MOVING_THRESHOLD": "0.10",
    "MOTION_MIN_SAMPLES": "3",
    "MOTION_MIN_TREND_CONSISTENCY": "0.60",
    "PARKING_CONFIRM_SECONDS": "600.0",
    "PARKING_MOVE_CONFIRM_SECONDS": "3.0",
    "TOF_I2C_BUS": "7",
    "TOF_SHUTDOWN_SETTLE_SECONDS": "0.01",
    "TOF_BOOT_SETTLE_SECONDS": "0.02",
    "TOF_IO_TIMEOUT_SECONDS": "1.0",
    "TOF_DISABLED_ZONE_ID": "4",
    "TOF_EV_CHARGING_ZONE_ID": "5",
    "TOF_POLL_INTERVAL_SECONDS": "0.05",
    "TOF_ENTER_DISTANCE_MM": "150.0",
    "TOF_EXIT_DISTANCE_MM": "220.0",
    "TOF_ENTER_CONFIRM_SECONDS": "0.0",
    "TOF_EXIT_CONFIRM_SECONDS": "0.0",
    "TOF_TRUSTED_SAMPLE_MAX_GAP_SECONDS": "1.0",
    "TOF_STALE_AFTER_SECONDS": "2.0",
}


@pytest.fixture(autouse=True)
def _required_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    # get_settings가 lru_cache라 앞선 테스트의 캐시가 남으면 주입이 무시된다.
    from src.config.settings import get_settings

    get_settings.cache_clear()
