"""환경변수에서 구성되는 Jetson 설정의 공개 계약 테스트."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.config.settings import Settings

TOF_OPTIONAL_ENV_FIELDS = (
    ("TOF_I2C_BUS", "tof_i2c_bus"),
    ("TOF_SHUTDOWN_SETTLE_SECONDS", "tof_shutdown_settle_seconds"),
    ("TOF_BOOT_SETTLE_SECONDS", "tof_boot_settle_seconds"),
    ("TOF_IO_TIMEOUT_SECONDS", "tof_io_timeout_seconds"),
    ("TOF_DISABLED_ZONE_ID", "tof_disabled_zone_id"),
    ("TOF_EV_CHARGING_ZONE_ID", "tof_ev_charging_zone_id"),
    ("TOF_POLL_INTERVAL_SECONDS", "tof_poll_interval_seconds"),
    ("TOF_ENTER_DISTANCE_MM", "tof_enter_distance_mm"),
    ("TOF_EXIT_DISTANCE_MM", "tof_exit_distance_mm"),
    ("TOF_ENTER_CONFIRM_SECONDS", "tof_enter_confirm_seconds"),
    ("TOF_EXIT_CONFIRM_SECONDS", "tof_exit_confirm_seconds"),
    (
        "TOF_TRUSTED_SAMPLE_MAX_GAP_SECONDS",
        "tof_trusted_sample_max_gap_seconds",
    ),
    ("TOF_STALE_AFTER_SECONDS", "tof_stale_after_seconds"),
    (
        "TOF_OCCUPANCY_FRESHNESS_SECONDS",
        "tof_occupancy_freshness_seconds",
    ),
    (
        "TOF_MONITORING_FRESHNESS_SECONDS",
        "tof_monitoring_freshness_seconds",
    ),
    (
        "TOF_MAX_PRE_OCCUPANCY_OBSERVATION_SECONDS",
        "tof_max_pre_occupancy_observation_seconds",
    ),
    (
        "TOF_DISABLED_ZONE_WARNING_WAV_PATH",
        "tof_disabled_zone_warning_wav_path",
    ),
    (
        "TOF_EV_ZONE_WARNING_WAV_PATH",
        "tof_ev_zone_warning_wav_path",
    ),
    ("TOF_WARNING_AUDIO_DEVICE", "tof_warning_audio_device"),
)

TOF_REEVALUATION_ENV_FIELDS = (
    (
        "TOF_REEVALUATION_INITIAL_BACKOFF_SECONDS",
        "tof_reevaluation_initial_backoff_seconds",
    ),
    (
        "TOF_REEVALUATION_MAX_BACKOFF_SECONDS",
        "tof_reevaluation_max_backoff_seconds",
    ),
    (
        "TOF_REEVALUATION_BACKOFF_MULTIPLIER",
        "tof_reevaluation_backoff_multiplier",
    ),
)


def test_tof_is_disabled_and_optional_settings_are_absent_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TOF_ENABLED", raising=False)
    for environment_name, _field_name in TOF_OPTIONAL_ENV_FIELDS:
        monkeypatch.delenv(environment_name, raising=False)
    for environment_name, _field_name in TOF_REEVALUATION_ENV_FIELDS:
        monkeypatch.delenv(environment_name, raising=False)
    monkeypatch.delenv("TOF_DIAGNOSTIC_INTERVAL_SECONDS", raising=False)

    settings = Settings(_env_file=None)

    assert settings.tof_enabled is False
    assert all(
        getattr(settings, field_name) is None
        for _environment_name, field_name in TOF_OPTIONAL_ENV_FIELDS
    )
    assert settings.tof_reevaluation_initial_backoff_seconds == 0.25
    assert settings.tof_reevaluation_max_backoff_seconds == 2.0
    assert settings.tof_reevaluation_backoff_multiplier == 2.0
    assert settings.tof_diagnostic_interval_seconds == 5.0


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    (("true", True), ("false", False)),
)
def test_tof_enabled_parses_boolean(
    monkeypatch: pytest.MonkeyPatch,
    raw_value: str,
    expected: bool,
) -> None:
    monkeypatch.setenv("TOF_ENABLED", raw_value)

    assert Settings(_env_file=None).tof_enabled is expected


def test_tof_enabled_rejects_invalid_boolean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TOF_ENABLED", "not-a-boolean")

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    error_fields = {error["loc"][0] for error in exc_info.value.errors()}
    assert error_fields == {"tof_enabled"}


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
    monkeypatch.setenv("TOF_DIAGNOSTIC_INTERVAL_SECONDS", "4.0")
    monkeypatch.setenv("TOF_OCCUPANCY_FRESHNESS_SECONDS", "5")
    monkeypatch.setenv("TOF_MONITORING_FRESHNESS_SECONDS", "6")
    monkeypatch.setenv(
        "TOF_MAX_PRE_OCCUPANCY_OBSERVATION_SECONDS",
        "2",
    )
    monkeypatch.setenv(
        "TOF_REEVALUATION_INITIAL_BACKOFF_SECONDS",
        "0.4",
    )
    monkeypatch.setenv(
        "TOF_REEVALUATION_MAX_BACKOFF_SECONDS",
        "3",
    )
    monkeypatch.setenv(
        "TOF_REEVALUATION_BACKOFF_MULTIPLIER",
        "1.5",
    )
    monkeypatch.setenv(
        "TOF_DISABLED_ZONE_WARNING_WAV_PATH",
        "unverified/disabled.wav",
    )
    monkeypatch.setenv(
        "TOF_EV_ZONE_WARNING_WAV_PATH",
        "unverified/ev.wav",
    )
    monkeypatch.setenv("TOF_WARNING_AUDIO_DEVICE", "plughw:CARD=Device,DEV=0")

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
        "tof_diagnostic_interval_seconds",
        "tof_occupancy_freshness_seconds",
        "tof_monitoring_freshness_seconds",
        "tof_max_pre_occupancy_observation_seconds",
        "tof_reevaluation_initial_backoff_seconds",
        "tof_reevaluation_max_backoff_seconds",
        "tof_reevaluation_backoff_multiplier",
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
    assert settings.tof_diagnostic_interval_seconds == 4.0
    assert settings.tof_occupancy_freshness_seconds == 5.0
    assert settings.tof_monitoring_freshness_seconds == 6.0
    assert settings.tof_max_pre_occupancy_observation_seconds == 2.0
    assert settings.tof_reevaluation_initial_backoff_seconds == 0.4
    assert settings.tof_reevaluation_max_backoff_seconds == 3.0
    assert settings.tof_reevaluation_backoff_multiplier == 1.5
    assert settings.tof_disabled_zone_warning_wav_path == Path(
        "unverified/disabled.wav"
    )
    assert settings.tof_ev_zone_warning_wav_path == Path("unverified/ev.wav")
    assert settings.tof_warning_audio_device == "plughw:CARD=Device,DEV=0"


def test_disabled_tof_rejects_provided_invalid_runtime_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TOF_ENABLED", "false")
    monkeypatch.setenv("TOF_I2C_BUS", "not-an-integer")

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    error_fields = {error["loc"][0] for error in exc_info.value.errors()}
    assert error_fields == {"tof_i2c_bus"}


def test_enabled_tof_allows_incomplete_runtime_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TOF_ENABLED", "true")
    monkeypatch.setenv("TOF_I2C_BUS", "7")

    settings = Settings(_env_file=None)

    assert settings.tof_enabled is True
    assert settings.tof_i2c_bus == 7
    assert settings.tof_boot_settle_seconds is None


def test_partial_speaker_configuration_is_preserved_for_runtime_isolation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TOF_ENABLED", "true")
    monkeypatch.setenv(
        "TOF_DISABLED_ZONE_WARNING_WAV_PATH",
        "unverified/disabled.wav",
    )

    settings = Settings(_env_file=None)

    assert settings.tof_enabled is True
    assert settings.tof_disabled_zone_warning_wav_path == Path(
        "unverified/disabled.wav"
    )
    assert settings.tof_ev_zone_warning_wav_path is None
    assert settings.tof_warning_audio_device is None


@pytest.mark.parametrize(
    ("environment_name", "field_name"),
    (
        (
            "TOF_DISABLED_ZONE_WARNING_WAV_PATH",
            "tof_disabled_zone_warning_wav_path",
        ),
        (
            "TOF_EV_ZONE_WARNING_WAV_PATH",
            "tof_ev_zone_warning_wav_path",
        ),
        ("TOF_WARNING_AUDIO_DEVICE", "tof_warning_audio_device"),
    ),
)
def test_tof_speaker_settings_reject_blank_strings(
    monkeypatch: pytest.MonkeyPatch,
    environment_name: str,
    field_name: str,
) -> None:
    monkeypatch.setenv(environment_name, "   ")

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    error_fields = {error["loc"][0] for error in exc_info.value.errors()}
    assert error_fields == {field_name}


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
