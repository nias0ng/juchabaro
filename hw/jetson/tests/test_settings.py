"""환경변수에서 구성되는 Jetson 설정의 공개 계약 테스트."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.config.settings import Settings


def test_tof_settings_parse_environment_variable_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TOF_I2C_BUS", "7")
    monkeypatch.setenv("TOF_SHUTDOWN_SETTLE_SECONDS", "0.01")
    monkeypatch.setenv("TOF_BOOT_SETTLE_SECONDS", "0.02")
    monkeypatch.setenv("TOF_IO_TIMEOUT_SECONDS", "1.0")
    monkeypatch.setenv("TOF_DISABLED_ZONE_ID", "4")
    monkeypatch.setenv("TOF_EV_CHARGING_ZONE_ID", "5")
    monkeypatch.setenv("TOF_POLL_INTERVAL_SECONDS", "0.05")
    monkeypatch.setenv("TOF_ENTER_DISTANCE_MM", "150")
    monkeypatch.setenv("TOF_EXIT_DISTANCE_MM", "220")
    monkeypatch.setenv("TOF_ENTER_CONFIRM_SECONDS", "0")
    monkeypatch.setenv("TOF_EXIT_CONFIRM_SECONDS", "0")
    monkeypatch.setenv(
        "TOF_TRUSTED_SAMPLE_MAX_GAP_SECONDS",
        "1.0",
    )
    monkeypatch.setenv("TOF_STALE_AFTER_SECONDS", "2.0")

    settings = Settings(_env_file=None)

    assert settings.tof_i2c_bus == 7
    assert isinstance(settings.tof_i2c_bus, int)
    assert settings.tof_shutdown_settle_seconds == 0.01
    assert settings.tof_boot_settle_seconds == 0.02
    assert settings.tof_io_timeout_seconds == 1.0
    assert isinstance(settings.tof_shutdown_settle_seconds, float)
    assert isinstance(settings.tof_boot_settle_seconds, float)
    assert isinstance(settings.tof_io_timeout_seconds, float)
    assert settings.tof_disabled_zone_id == 4
    assert settings.tof_ev_charging_zone_id == 5
    assert isinstance(settings.tof_disabled_zone_id, int)
    assert isinstance(settings.tof_ev_charging_zone_id, int)

    float_fields = (
        "tof_poll_interval_seconds",
        "tof_enter_distance_mm",
        "tof_exit_distance_mm",
        "tof_enter_confirm_seconds",
        "tof_exit_confirm_seconds",
        "tof_trusted_sample_max_gap_seconds",
        "tof_stale_after_seconds",
    )
    assert all(
        isinstance(getattr(settings, field_name), float)
        for field_name in float_fields
    )
    assert settings.tof_poll_interval_seconds == 0.05
    assert settings.tof_enter_distance_mm == 150.0
    assert settings.tof_exit_distance_mm == 220.0
    assert settings.tof_enter_confirm_seconds == 0.0
    assert settings.tof_exit_confirm_seconds == 0.0
    assert settings.tof_trusted_sample_max_gap_seconds == 1.0
    assert settings.tof_stale_after_seconds == 2.0


@pytest.mark.parametrize(
    "environment_name,field_name",
    [
        ("TOF_I2C_BUS", "tof_i2c_bus"),
        (
            "TOF_SHUTDOWN_SETTLE_SECONDS",
            "tof_shutdown_settle_seconds",
        ),
        (
            "TOF_BOOT_SETTLE_SECONDS",
            "tof_boot_settle_seconds",
        ),
        (
            "TOF_IO_TIMEOUT_SECONDS",
            "tof_io_timeout_seconds",
        ),
        ("TOF_DISABLED_ZONE_ID", "tof_disabled_zone_id"),
        (
            "TOF_EV_CHARGING_ZONE_ID",
            "tof_ev_charging_zone_id",
        ),
        (
            "TOF_POLL_INTERVAL_SECONDS",
            "tof_poll_interval_seconds",
        ),
        (
            "TOF_ENTER_DISTANCE_MM",
            "tof_enter_distance_mm",
        ),
        (
            "TOF_EXIT_DISTANCE_MM",
            "tof_exit_distance_mm",
        ),
        (
            "TOF_ENTER_CONFIRM_SECONDS",
            "tof_enter_confirm_seconds",
        ),
        (
            "TOF_EXIT_CONFIRM_SECONDS",
            "tof_exit_confirm_seconds",
        ),
        (
            "TOF_TRUSTED_SAMPLE_MAX_GAP_SECONDS",
            "tof_trusted_sample_max_gap_seconds",
        ),
        (
            "TOF_STALE_AFTER_SECONDS",
            "tof_stale_after_seconds",
        ),
    ],
)
def test_tof_settings_are_required(
    monkeypatch: pytest.MonkeyPatch,
    environment_name: str,
    field_name: str,
) -> None:
    monkeypatch.delenv(environment_name)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    missing_fields = {
        error["loc"][0]
        for error in exc_info.value.errors()
        if error["type"] == "missing"
    }
    assert field_name in missing_fields


def test_live_stream_is_disabled_by_default() -> None:
    """운영 배포가 MJPEG 인코딩 비용을 기본으로 떠안지 않는다."""

    settings = Settings(_env_file=None)

    assert settings.live_stream_enabled is False
    assert settings.live_stream_target_fps == 15.0
    assert settings.live_stream_jpeg_quality == 80


def test_live_stream_settings_parse_environment_variable_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LIVE_STREAM_ENABLED", "true")
    monkeypatch.setenv("LIVE_STREAM_TARGET_FPS", "10.0")
    monkeypatch.setenv("LIVE_STREAM_JPEG_QUALITY", "60")

    settings = Settings(_env_file=None)

    assert settings.live_stream_enabled is True
    assert settings.live_stream_target_fps == 10.0
    assert settings.live_stream_jpeg_quality == 60


def test_live_stream_rejects_non_positive_target_fps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LIVE_STREAM_TARGET_FPS", "0")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_remap_backend_defaults_to_opencv() -> None:
    settings = Settings(_env_file=None)

    assert settings.remap_backend == "opencv"


def test_remap_backend_is_normalized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REMAP_BACKEND", " VPI ")

    settings = Settings(_env_file=None)

    assert settings.remap_backend == "vpi"


def test_remap_backend_rejects_unknown_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REMAP_BACKEND", "cuda")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
