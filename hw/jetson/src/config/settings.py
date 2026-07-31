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

    # 입차 이벤트 매칭 대기 시간(초). 383의 기본값을 그대로 따른다 —
    # 실측 튜닝이 필요해지면 zone_entry_confirm_seconds처럼 기본값을 없앨 수 있다.
    entry_match_window_seconds: float = 10.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()