from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Smart Parking Jetson API"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"

    backend_base_url: str = "http://localhost:8080"

    hw_api_key: str = ""
    internal_api_key: str = ""

    # 구역 방문 확인시간(초). 기본값을 두지 않는 이유는 스펙 §4.7에 있다 —
    # zone_entry_confirm_seconds가 전용구역 진입 즉시 판정의 유일한 오탐
    # 방어선이고, 실측값은 T-18이 파일럿 영상 리플레이로 산출한다.
    zone_entry_confirm_seconds: float
    zone_exit_confirm_seconds: float

    # 주차 확정 임계값(초). 600초는 요구사항이 정한 값이고,
    # parking_move_confirm_seconds는 파일럿 영상으로 산출해야 하는 값이다 —
    # motion_estimator에 평활화가 없어 이 값이 잡음으로 인한 주차 종료를 막는
    # 유일한 방어선이다.
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