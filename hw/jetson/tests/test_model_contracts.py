"""Jetson과 하드웨어 어댑터 사이의 입출력 모델 계약.

이 테스트는 실제 GPIO, 센서, LED, speaker 동작을 검증하지 않는다.
하드웨어 담당 어댑터가 제공할 센서 입력과 내부 파이프라인이
생성할 actuator 출력의 최소 경계가 리팩터링 중 사라지지 않게 고정한다.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.actuators.models import ActuatorCommand
from src.sensors.models import SensorObservation


NOW = datetime(2026, 7, 31, 12, 0, 0, tzinfo=timezone.utc)


def test_sensor_observation_preserves_raw_hardware_input_contract() -> None:
    observation = SensorObservation(
        sensor_id="us-1",
        sensor_type="ultrasonic",
        value=42.0,
        observed_at=NOW,
    )

    assert observation.sensor_id == "us-1"
    assert observation.sensor_type == "ultrasonic"
    assert observation.value == 42.0
    assert observation.observed_at == NOW
    assert observation.quality is None


def test_actuator_command_preserves_hardware_output_contract() -> None:
    command = ActuatorCommand(
        actuator_id="led-1",
        action="BLINK",
        reason="EV_OVERSTAY",
        requested_at=NOW,
    )

    assert command.actuator_id == "led-1"
    assert command.action == "BLINK"
    assert command.reason == "EV_OVERSTAY"
    assert command.requested_at == NOW
