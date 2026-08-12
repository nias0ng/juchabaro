"""ToF 전용구역 권한 평가를 process-local 경고 projection으로 변환한다.

이 모듈은 구역별 로컬 경고 상태와 LED·speaker 전체 projection만 관리한다.
권한 판정, Incident, 영속화, 장치 lifecycle 및 runtime 조립은 소유하지 않는다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from threading import Lock

from src.actuators.models import ActuatorCommand
from src.actuators.ports import ActuatorPort
from src.application.sensor_occupancy import OccupancyState
from src.application.tof_zone_authorization import (
    TofAuthorizationDecision,
    TofAuthorizationReason,
    TofZoneAuthorizationAssessment,
)
from src.domain.models import require_aware
from src.parking.models import ZoneId, ZoneType


logger = logging.getLogger(__name__)

_WARNING_REASON = "TOF_ZONE_UNAUTHORIZED"
_SUPPORTED_ZONE_TYPES = frozenset(
    {
        ZoneType.DISABLED,
        ZoneType.EV_CHARGING,
    }
)


def _require_non_blank(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name}은 공백이 아닌 문자열이어야 합니다.")


@dataclass(frozen=True, kw_only=True)
class LocalWarningZoneBinding:
    """전용구역 하나와 해당 로컬 경고 actuator 명령을 결속한다."""

    zone_id: ZoneId
    zone_type: ZoneType
    led_actuator_id: str
    led_action: str
    speaker_actuator_id: str
    speaker_action: str

    def __post_init__(self) -> None:
        if (
            isinstance(self.zone_id, bool)
            or not isinstance(self.zone_id, int)
            or self.zone_id <= 0
        ):
            raise ValueError("zone_id는 양의 정수여야 합니다.")
        if (
            not isinstance(self.zone_type, ZoneType)
            or self.zone_type not in _SUPPORTED_ZONE_TYPES
        ):
            raise ValueError(
                "zone_type은 DISABLED 또는 EV_CHARGING이어야 합니다."
            )

        _require_non_blank(self.led_actuator_id, "led_actuator_id")
        _require_non_blank(self.led_action, "led_action")
        _require_non_blank(
            self.speaker_actuator_id,
            "speaker_actuator_id",
        )
        _require_non_blank(self.speaker_action, "speaker_action")


class LocalWarningAssessmentConflictError(ValueError):
    """같은 zone revision에 서로 다른 assessment가 전달된 계약 오류."""

    def __init__(
        self,
        *,
        zone_id: ZoneId,
        assessment_revision: int,
        existing_assessment: TofZoneAuthorizationAssessment,
        incoming_assessment: TofZoneAuthorizationAssessment,
    ) -> None:
        super().__init__(
            "동일한 assessment revision에 서로 다른 평가가 전달되었습니다: "
            f"zone_id={zone_id}, "
            f"assessment_revision={assessment_revision}"
        )
        self.zone_id = zone_id
        self.assessment_revision = assessment_revision
        self.existing_assessment = existing_assessment
        self.incoming_assessment = incoming_assessment


class LocalWarningDeliveryStage(str, Enum):
    LED = "LED"
    SPEAKER = "SPEAKER"


@dataclass(frozen=True)
class LocalWarningDeliveryFailure:
    """한 actuator port에 projection을 전달하지 못한 결과."""

    stage: LocalWarningDeliveryStage
    error: Exception

    def __post_init__(self) -> None:
        if not isinstance(self.stage, LocalWarningDeliveryStage):
            raise ValueError(
                "stage는 LocalWarningDeliveryStage여야 합니다."
            )
        if not isinstance(self.error, Exception):
            raise ValueError("error는 Exception이어야 합니다.")


class LocalWarningDeliveryError(RuntimeError):
    """하나 이상의 actuator port projection 전달 실패."""

    def __init__(
        self,
        *,
        failures: tuple[LocalWarningDeliveryFailure, ...],
        active_zone_ids: tuple[ZoneId, ...],
    ) -> None:
        if not isinstance(failures, tuple) or not failures:
            raise ValueError(
                "failures는 비어 있지 않은 tuple이어야 합니다."
            )
        if any(
            not isinstance(failure, LocalWarningDeliveryFailure)
            for failure in failures
        ):
            raise ValueError(
                "failures의 모든 항목은 "
                "LocalWarningDeliveryFailure여야 합니다."
            )

        self.failures = failures
        self.primary_error = failures[0].error
        self.active_zone_ids = active_zone_ids

        details = "; ".join(
            f"{failure.stage.value}: {failure.error}"
            for failure in failures
        )
        super().__init__(
            "로컬 경고 projection 전달에 실패했습니다: "
            f"{details}"
        )


@dataclass(frozen=True, kw_only=True)
class _LocalWarningZoneState:
    warning_active: bool
    warning_started_at: datetime | None

    def __post_init__(self) -> None:
        if self.warning_active:
            if self.warning_started_at is None:
                raise ValueError(
                    "활성 경고에는 warning_started_at이 필요합니다."
                )
            require_aware(
                self.warning_started_at,
                "warning_started_at",
            )
        elif self.warning_started_at is not None:
            raise ValueError(
                "비활성 경고에는 warning_started_at을 둘 수 없습니다."
            )


class _AssessmentAcceptance(Enum):
    NEW = auto()
    RETRY = auto()
    STALE = auto()


@dataclass
class _ProjectionDeliveryState:
    last_successful_projection: tuple[ActuatorCommand, ...] = ()
    dirty: bool = False


_INACTIVE_STATE = _LocalWarningZoneState(
    warning_active=False,
    warning_started_at=None,
)


class LocalWarningCoordinator:
    """ToF assessment를 LED·speaker 전체 경고 projection으로 반영한다."""

    def __init__(
        self,
        *,
        bindings: tuple[LocalWarningZoneBinding, ...],
        led_port: ActuatorPort,
        speaker_port: ActuatorPort,
    ) -> None:
        self._bindings = self._validate_bindings(bindings)

        for port, field_name in (
            (led_port, "led_port"),
            (speaker_port, "speaker_port"),
        ):
            if not callable(getattr(port, "apply_projection", None)):
                raise ValueError(
                    f"{field_name}.apply_projection은 callable이어야 합니다."
                )

        self._led_port = led_port
        self._speaker_port = speaker_port

        self._lock = Lock()
        self._states = {
            zone_id: _INACTIVE_STATE
            for zone_id in self._bindings
        }
        self._latest_assessments: dict[
            ZoneId,
            TofZoneAuthorizationAssessment,
        ] = {}

        # Adapter의 초기 상태도 경고가 없는 빈 projection이라는 계약을 따른다.
        self._led_delivery_state = _ProjectionDeliveryState()
        self._speaker_delivery_state = _ProjectionDeliveryState()

    def consume_assessment(
        self,
        assessment: TofZoneAuthorizationAssessment,
    ) -> None:
        """Assessment 하나를 수락하고 필요한 전체 projection을 전달한다."""

        if not isinstance(assessment, TofZoneAuthorizationAssessment):
            raise ValueError(
                "assessment는 TofZoneAuthorizationAssessment여야 합니다."
            )

        with self._lock:
            binding = self._bindings.get(assessment.zone_id)
            if binding is None:
                raise ValueError(
                    "등록되지 않은 로컬 경고 zone_id입니다: "
                    f"{assessment.zone_id}"
                )
            if (
                assessment.zone_type is not None
                and assessment.zone_type is not binding.zone_type
            ):
                raise ValueError(
                    "assessment.zone_type이 binding과 일치하지 않습니다: "
                    f"zone_id={assessment.zone_id}"
                )

            acceptance = self._accept_assessment(assessment)
            if acceptance is _AssessmentAcceptance.STALE:
                return
            previous_active_zone_ids = self._active_zone_ids_unlocked()
            if acceptance is _AssessmentAcceptance.NEW:
                self._update_state(assessment)

            led_projection, speaker_projection = self._build_projections()
            failures: list[LocalWarningDeliveryFailure] = []

            led_failure = self._reconcile_port(
                stage=LocalWarningDeliveryStage.LED,
                port=self._led_port,
                delivery_state=self._led_delivery_state,
                desired_projection=led_projection,
            )
            if led_failure is not None:
                failures.append(led_failure)

            speaker_failure = self._reconcile_port(
                stage=LocalWarningDeliveryStage.SPEAKER,
                port=self._speaker_port,
                delivery_state=self._speaker_delivery_state,
                desired_projection=speaker_projection,
            )
            if speaker_failure is not None:
                failures.append(speaker_failure)

            if failures:
                delivery_error = self._build_delivery_error(
                    tuple(failures)
                )
                raise delivery_error from delivery_error.primary_error

            active_zone_ids = self._active_zone_ids_unlocked()
            if active_zone_ids != previous_active_zone_ids:
                logger.info(
                    "Jetson ToF local warning changed. "
                    "zoneId=%d decision=%s activeZoneIds=%s "
                    "ledCommandCount=%d speakerCommandCount=%d",
                    int(assessment.zone_id),
                    (
                        assessment.decision.value
                        if assessment.decision is not None
                        else "-"
                    ),
                    ",".join(str(int(zone_id)) for zone_id in active_zone_ids)
                    or "-",
                    len(led_projection),
                    len(speaker_projection),
                )

    def active_zone_ids(self) -> tuple[ZoneId, ...]:
        """현재 로컬 경고가 활성화된 zone ID를 정렬해 반환한다."""

        with self._lock:
            return self._active_zone_ids_unlocked()

    @staticmethod
    def _validate_bindings(
        bindings: tuple[LocalWarningZoneBinding, ...],
    ) -> dict[ZoneId, LocalWarningZoneBinding]:
        if not isinstance(bindings, tuple) or not bindings:
            raise ValueError(
                "bindings는 비어 있지 않은 tuple이어야 합니다."
            )

        by_zone_id: dict[ZoneId, LocalWarningZoneBinding] = {}
        led_actuator_ids: set[str] = set()
        speaker_actuator_ids: set[str] = set()

        for binding in bindings:
            if not isinstance(binding, LocalWarningZoneBinding):
                raise ValueError(
                    "bindings의 모든 항목은 "
                    "LocalWarningZoneBinding이어야 합니다."
                )
            if binding.zone_id in by_zone_id:
                raise ValueError(
                    f"zone_id가 중복되었습니다: {binding.zone_id}"
                )
            if binding.led_actuator_id in led_actuator_ids:
                raise ValueError(
                    "LED actuator_id가 중복되었습니다: "
                    f"{binding.led_actuator_id!r}"
                )
            if binding.speaker_actuator_id in speaker_actuator_ids:
                raise ValueError(
                    "speaker actuator_id가 중복되었습니다: "
                    f"{binding.speaker_actuator_id!r}"
                )

            by_zone_id[binding.zone_id] = binding
            led_actuator_ids.add(binding.led_actuator_id)
            speaker_actuator_ids.add(binding.speaker_actuator_id)

        zone_type_counts = {
            zone_type: sum(
                binding.zone_type is zone_type
                for binding in bindings
            )
            for zone_type in _SUPPORTED_ZONE_TYPES
        }
        invalid_counts = {
            zone_type: count
            for zone_type, count in zone_type_counts.items()
            if count != 1
        }
        if invalid_counts:
            details = ", ".join(
                f"{zone_type.value}={count}"
                for zone_type, count in sorted(
                    invalid_counts.items(),
                    key=lambda item: item[0].value,
                )
            )
            raise ValueError(
                "DISABLED와 EV_CHARGING binding이 각각 하나씩 "
                f"필요합니다: {details}"
            )

        return by_zone_id

    def _accept_assessment(
        self,
        assessment: TofZoneAuthorizationAssessment,
    ) -> _AssessmentAcceptance:
        revision = assessment.assessment_revision
        if revision < 1:
            raise ValueError("assessment_revision은 1 이상이어야 합니다.")

        existing = self._latest_assessments.get(assessment.zone_id)
        if existing is None:
            self._latest_assessments[assessment.zone_id] = assessment
            return _AssessmentAcceptance.NEW

        if revision > existing.assessment_revision:
            self._latest_assessments[assessment.zone_id] = assessment
            return _AssessmentAcceptance.NEW

        if revision < existing.assessment_revision:
            return _AssessmentAcceptance.STALE

        if assessment == existing:
            return _AssessmentAcceptance.RETRY

        raise LocalWarningAssessmentConflictError(
            zone_id=assessment.zone_id,
            assessment_revision=revision,
            existing_assessment=existing,
            incoming_assessment=assessment,
        )

    def _update_state(
        self,
        assessment: TofZoneAuthorizationAssessment,
    ) -> None:
        current = self._states[assessment.zone_id]

        if assessment.decision is TofAuthorizationDecision.UNAUTHORIZED:
            if not current.warning_active:
                self._states[assessment.zone_id] = (
                    _LocalWarningZoneState(
                        warning_active=True,
                        warning_started_at=assessment.evaluated_at,
                    )
                )
            return

        should_clear = (
            assessment.decision is TofAuthorizationDecision.AUTHORIZED
            or (
                assessment.occupancy_state is OccupancyState.VACANT
                and assessment.reason
                is TofAuthorizationReason.ZONE_VACANT
            )
        )
        if should_clear and current.warning_active:
            self._states[assessment.zone_id] = _INACTIVE_STATE

        # UNKNOWN과 그 밖의 미확정 결과는 관측 불확실성만으로 기존 경고를
        # 해제하지 않도록 현재 상태를 유지한다.

    def _build_projections(
        self,
    ) -> tuple[
        tuple[ActuatorCommand, ...],
        tuple[ActuatorCommand, ...],
    ]:
        led_commands: list[ActuatorCommand] = []
        speaker_commands: list[ActuatorCommand] = []

        # Adapter는 증분 명령이 아닌 전체 목표 상태를 받으므로 모든 활성
        # 구역을 매번 안정적인 zone ID 순서로 다시 구성한다.
        for zone_id in sorted(self._states):
            state = self._states[zone_id]
            if not state.warning_active:
                continue

            warning_started_at = state.warning_started_at
            assert warning_started_at is not None
            binding = self._bindings[zone_id]

            led_commands.append(
                ActuatorCommand(
                    actuator_id=binding.led_actuator_id,
                    action=binding.led_action,
                    reason=_WARNING_REASON,
                    requested_at=warning_started_at,
                )
            )
            speaker_commands.append(
                ActuatorCommand(
                    actuator_id=binding.speaker_actuator_id,
                    action=binding.speaker_action,
                    reason=_WARNING_REASON,
                    requested_at=warning_started_at,
                )
            )

        return tuple(led_commands), tuple(speaker_commands)

    @staticmethod
    def _reconcile_port(
        *,
        stage: LocalWarningDeliveryStage,
        port: ActuatorPort,
        delivery_state: _ProjectionDeliveryState,
        desired_projection: tuple[ActuatorCommand, ...],
    ) -> LocalWarningDeliveryFailure | None:
        if (
            not delivery_state.dirty
            and desired_projection
            == delivery_state.last_successful_projection
        ):
            return None

        try:
            port.apply_projection(desired_projection)
        except Exception as error:
            # Port가 명령 적용 전후 중 언제 실패했는지 application 계층은
            # 확정할 수 없으므로 다음 수락 입력에서 반드시 재조정한다.
            delivery_state.dirty = True
            return LocalWarningDeliveryFailure(
                stage=stage,
                error=error,
            )

        delivery_state.last_successful_projection = desired_projection
        delivery_state.dirty = False
        return None

    def _build_delivery_error(
        self,
        failures: tuple[LocalWarningDeliveryFailure, ...],
    ) -> LocalWarningDeliveryError:
        return LocalWarningDeliveryError(
            failures=failures,
            active_zone_ids=self._active_zone_ids_unlocked(),
        )

    def _active_zone_ids_unlocked(self) -> tuple[ZoneId, ...]:
        return tuple(
            zone_id
            for zone_id in sorted(self._states)
            if self._states[zone_id].warning_active
        )
