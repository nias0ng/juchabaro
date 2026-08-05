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

    settings = Settings(_env_file=None)

    assert settings.tof_i2c_bus == 7
    assert isinstance(settings.tof_i2c_bus, int)
    assert settings.tof_shutdown_settle_seconds == 0.01
    assert settings.tof_boot_settle_seconds == 0.02
    assert settings.tof_io_timeout_seconds == 1.0
    assert isinstance(settings.tof_shutdown_settle_seconds, float)
    assert isinstance(settings.tof_boot_settle_seconds, float)
    assert isinstance(settings.tof_io_timeout_seconds, float)


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
