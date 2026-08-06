"""Jetson과 하드웨어 어댑터 사이의 입출력 모델 계약.

이 테스트는 실제 GPIO, 센서, LED, speaker 동작을 검증하지 않는다.
하드웨어 담당 어댑터가 제공할 센서 입력과 내부 파이프라인이
생성할 actuator 출력의 최소 경계가 리팩터링 중 사라지지 않게 고정한다.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.actuators.models import ActuatorCommand
from src.sensors.models import (
    TOF_SENSOR_TYPE,
    SensorObservation,
    SensorReadBatch,
    SensorReadFailure,
    SensorReadFailureReason,
)


NOW = datetime(2026, 7, 31, 12, 0, 0, tzinfo=timezone.utc)


def test_sensor_observation_preserves_tof_distance_contract() -> None:
    """ToF value가 mm 단위 원시 거리로 보존되는지 검증한다."""

    observation = SensorObservation(
        sensor_id="tof_disabled_zone",
        sensor_type=TOF_SENSOR_TYPE,
        value=420.0,
        observed_at=NOW,
    )

    assert observation.sensor_id == "tof_disabled_zone"
    assert observation.sensor_type == "tof"
    assert observation.value == 420.0
    assert observation.observed_at == NOW
    assert observation.quality is None


def test_sensor_read_failure_reasons_preserve_public_values() -> None:
    assert {reason.value for reason in SensorReadFailureReason} == {
        "TIMEOUT",
        "COMMUNICATION_ERROR",
        "OUT_OF_RANGE",
        "INVALID_READING",
    }


def test_sensor_read_batch_preserves_partial_success() -> None:
    observation = SensorObservation(
        sensor_id="tof_disabled_zone",
        sensor_type=TOF_SENSOR_TYPE,
        value=420.0,
        observed_at=NOW,
    )
    failure = SensorReadFailure(
        sensor_id="tof_ev_charging_zone",
        observed_at=NOW,
        reason=SensorReadFailureReason.TIMEOUT,
        message="측정 완료 대기시간을 초과했습니다.",
    )

    batch = SensorReadBatch(
        observations=(observation,),
        failures=(failure,),
    )

    assert batch.observations == (observation,)
    assert batch.failures == (failure,)
    assert failure.sensor_id == "tof_ev_charging_zone"
    assert failure.observed_at == NOW
    assert failure.reason is SensorReadFailureReason.TIMEOUT
    assert failure.message == "측정 완료 대기시간을 초과했습니다."


def test_sensor_read_batch_allows_empty_results() -> None:
    """센서 개수 검증은 batch 모델의 책임이 아니므로 빈 결과를 허용한다."""

    batch = SensorReadBatch(observations=(), failures=())

    assert batch.observations == ()
    assert batch.failures == ()


def test_sensor_read_batch_rejects_duplicate_observation_sensor_ids() -> None:
    first_observation = SensorObservation(
        sensor_id="tof_disabled_zone",
        sensor_type=TOF_SENSOR_TYPE,
        value=420.0,
        observed_at=NOW,
    )
    second_observation = SensorObservation(
        sensor_id="tof_disabled_zone",
        sensor_type=TOF_SENSOR_TYPE,
        value=430.0,
        observed_at=NOW,
    )

    with pytest.raises(ValueError) as exc_info:
        SensorReadBatch(
            observations=(first_observation, second_observation),
            failures=(),
        )

    message = str(exc_info.value)
    assert "observations" in message
    assert "tof_disabled_zone" in message


def test_sensor_read_batch_rejects_duplicate_failure_sensor_ids() -> None:
    first_failure = SensorReadFailure(
        sensor_id="tof_ev_charging_zone",
        observed_at=NOW,
        reason=SensorReadFailureReason.TIMEOUT,
        message="측정 완료 대기시간을 초과했습니다.",
    )
    second_failure = SensorReadFailure(
        sensor_id="tof_ev_charging_zone",
        observed_at=NOW,
        reason=SensorReadFailureReason.COMMUNICATION_ERROR,
        message="센서와 통신할 수 없습니다.",
    )

    with pytest.raises(ValueError) as exc_info:
        SensorReadBatch(
            observations=(),
            failures=(first_failure, second_failure),
        )

    message = str(exc_info.value)
    assert "failures" in message
    assert "tof_ev_charging_zone" in message


def test_sensor_read_batch_rejects_same_sensor_as_success_and_failure() -> None:
    observation = SensorObservation(
        sensor_id="tof_disabled_zone",
        sensor_type=TOF_SENSOR_TYPE,
        value=420.0,
        observed_at=NOW,
    )
    failure = SensorReadFailure(
        sensor_id="tof_disabled_zone",
        observed_at=NOW,
        reason=SensorReadFailureReason.INVALID_READING,
        message="센서 결과를 유효한 거리로 해석할 수 없습니다.",
    )

    with pytest.raises(ValueError) as exc_info:
        SensorReadBatch(
            observations=(observation,),
            failures=(failure,),
        )

    message = str(exc_info.value)
    assert "observations와 failures" in message
    assert "tof_disabled_zone" in message


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
