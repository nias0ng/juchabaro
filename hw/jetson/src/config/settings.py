from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Smart Parking Jetson API"
    log_level: str = "INFO"

    backend_base_url: str = "https://i15e202.p.ssafy.io/"
    backend_hw_api_key: str = ""

    internal_api_key: str = ""

    # Jetson local durable state. 요청 thread와 tracking worker는 각자
    # connection을 열고 SQLite file만 공유한다.
    database_path: Path

    # Evidence binary는 DB BLOB이 아니라 동일 장치의 제한된 spool에 둔다.
    # cap은 설치 완료 뒤 장치 여유공간을 확인해 배포가 직접 정하며, 일반
    # restart에서 현재 free space를 새 baseline으로 저장하지 않는다.
    evidence_spool_path: Path
    evidence_spool_cap_bytes: int

    # 아래 retention·filesystem 비율은 pilot 실측 전 제안값이다. 전역
    # DB/WAL/log admission DRAIN은 write-size ADR과 application wiring 범위다.
    evidence_filesystem_floor_ratio: float = 0.30
    evidence_capture_stop_free_ratio: float = 0.35
    evidence_ack_retention_seconds: float = 24 * 60 * 60
    evidence_unacked_retention_seconds: float = 7 * 24 * 60 * 60

    # 한 배포의 versioned ZoneDefinition JSON. 실행 중 hot replacement는 하지
    # 않으며, 기동 조립 단계에서 ZoneRegistry가 파일 전체를 검증한다.
    zone_definition_path: Path

    # 구역 방문 확인시간(초). 기본값을 두지 않는 이유는 스펙 §4.7에 있다 —
    # zone_entry_confirm_seconds가 전용구역 진입 즉시 판정의 유일한 오탐
    # 방어선이고, 실측값은 T-18이 파일럿 영상 리플레이로 산출한다.
    zone_entry_confirm_seconds: float
    zone_exit_confirm_seconds: float

    # 입차 이벤트 매칭 대기 시간(초). 383의 기본값을 그대로 따른다 —
    # 실측 튜닝이 필요해지면 zone_entry_confirm_seconds처럼 기본값을 없앨 수 있다.
    entry_match_window_seconds: float = 10.0

    # Tracker timeout과 분리된 PhysicalVehicle 부재 확정 시간(초).
    # 정상 전체 구역 관측만 누적하며, 시연값도 배포별로 명시한다.
    absence_confirmation_seconds: float

    # 연속 trusted sample로 인정할 최대 프레임 간격. 이를 넘는
    # capture·inference stall은 부재 확정 시간으로 보충하지 않는다.
    trusted_sample_max_gap_seconds: float

    # bbox 시간 창에서만 계산하는 ephemeral motion evidence 정책. 거리 임계값은
    # median bbox diagonal 대비 비율이며, 아래 값은 파일럿 replay로 재조정한다.
    # 이 owner는 identity·zone·parking lifecycle을 판단하지 않는다.
    motion_window_seconds: float
    motion_min_observation_span_seconds: float
    motion_max_sample_gap_seconds: float
    motion_stationary_threshold: float
    motion_moving_threshold: float
    motion_min_samples: int
    motion_min_trend_consistency: float

    # 주차 확정 임계값(초). 600초는 요구사항이 정한 값이고,
    # parking_move_confirm_seconds는 파일럿 영상으로 산출해야 하는 값이다.
    # MotionEstimator의 evidence 임계값과 별개인 ParkingEpisode lifecycle timer다.
    parking_confirm_seconds: float
    parking_move_confirm_seconds: float

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
