"""시작하지 않은 ToF 로컬 경고 runtime 구성요소를 조립한다.

이 모듈은 sensor occupancy, authorization 및 local warning 구성요소의 dependency
wiring만 담당한다. 장치 생성·open, worker lifecycle, rollback, shutdown orchestration
및 FastAPI lifespan 연결은 후속 production composition 계층의 책임이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.actuators.adapters.jetson_gpio_led import (
    BLINK_ACTION,
    DISABLED_ZONE_WARNING_LED_ID,
    EV_ZONE_WARNING_LED_ID,
)
from src.actuators.adapters.jetson_usb_speaker import (
    DISABLED_ZONE_WARNING_SPEAKER_ID,
    EV_ZONE_WARNING_SPEAKER_ID,
    PLAY_ACTION,
)
from src.actuators.ports import ActuatorPort
from src.application.local_warning_coordinator import (
    LocalWarningCoordinator,
    LocalWarningZoneBinding,
)
from src.application.sensor_factory import (
    TofSensorRuntimeDependencies,
    TofSensorRuntimePolicy,
    build_tof_sensor_worker,
)
from src.application.sensor_worker import SensorWorker
from src.application.tof_authorization_worker import (
    TofAuthorizationRequestMailbox,
    TofAuthorizationReevaluationPolicy,
    TofAuthorizationWorker,
)
from src.application.tof_monitoring_projection import (
    LatestTofMonitoringProjectionStore,
    TofMonitoringProjectionUpdate,
)
from src.application.tof_zone_authorization import (
    RepositoryTofZoneAuthorizationQuery,
    TofAuthorizationPolicy,
    TofZoneAuthorizationService,
)
from src.application.tof_zone_authorization_coordinator import (
    ConnectionFactory,
    TofZoneAuthorizationCoordinator,
)
from src.parking.models import ZoneType
from src.parking.zone_registry import ZoneRegistry
from src.sensors.ports import SensorArray


@dataclass(frozen=True, kw_only=True)
class TofWarningRuntimePolicy:
    """ToF occupancy와 authorization domain 정책."""

    sensor: TofSensorRuntimePolicy
    authorization: TofAuthorizationPolicy
    reevaluation: TofAuthorizationReevaluationPolicy = field(
        default_factory=TofAuthorizationReevaluationPolicy,
    )


@dataclass(frozen=True, kw_only=True)
class TofWarningRuntimeDependencies:
    """상위 production composition이 제공하는 외부 의존성."""

    sensor_array: SensorArray
    led_port: ActuatorPort
    speaker_port: ActuatorPort
    connection_factory: ConnectionFactory


@dataclass(frozen=True, kw_only=True)
class TofWarningRuntime:
    """아직 시작하지 않은 ToF 경고 runtime 구성요소."""

    sensor_worker: SensorWorker
    authorization_coordinator: TofZoneAuthorizationCoordinator
    authorization_worker: TofAuthorizationWorker
    local_warning_coordinator: LocalWarningCoordinator
    _mailbox: TofAuthorizationRequestMailbox = field(
        repr=False,
        compare=False,
    )
    _monitoring_projection_store: LatestTofMonitoringProjectionStore = field(
        repr=False,
        compare=False,
    )

    def publish_monitoring_projection(
        self,
        update: TofMonitoringProjectionUpdate,
    ) -> None:
        """최신 camera monitoring 상태를 ToF 전용 volatile projection에 반영한다."""

        self._monitoring_projection_store.publish(update)

    def request_after_monitoring_context_change(self) -> None:
        """ToF 판정 문맥 변경이 commit된 뒤 재평가 신호만 등록한다.

        모든 monitoring frame commit마다 호출하는 callback이 아니다. 차량,
        session 또는 zone visit 등 판정 문맥이 변경될 가능성이 있는 transaction의
        commit 이후 호출한다. FrameObservationResult 기반 호출 조건은 후속
        composition 계층에서 결정한다.
        """

        self._mailbox.request_after_monitoring_commit()

    def request_after_monitoring_frame_commit(
        self,
        *,
        context_changed: bool = False,
    ) -> None:
        """정상 monitoring frame의 one-shot 재평가 신호를 등록한다.

        semantic context 변경이 같은 frame에서 감지된 경우 두 mailbox
        flag를 원자적으로 등록해 동일 frame 중복 평가를 방지한다.
        """

        self._mailbox.request_after_monitoring_frame_commit(
            context_changed=context_changed,
        )


def build_tof_warning_runtime(
    *,
    zones: ZoneRegistry,
    policy: TofWarningRuntimePolicy,
    dependencies: TofWarningRuntimeDependencies,
) -> TofWarningRuntime:
    """검증된 정책과 주입된 port로 시작하지 않은 runtime을 조립한다."""

    mailbox = TofAuthorizationRequestMailbox()
    monitoring_projection_store = LatestTofMonitoringProjectionStore(
        target_zone_ids=(
            policy.sensor.disabled_zone_id,
            policy.sensor.ev_charging_zone_id,
        ),
    )
    sensor_worker = build_tof_sensor_worker(
        zones=zones,
        policy=policy.sensor,
        dependencies=TofSensorRuntimeDependencies(
            sensor_array=dependencies.sensor_array,
            transition_consumer=mailbox.request_transitions,
        ),
    )

    local_warning_coordinator = LocalWarningCoordinator(
        bindings=(
            LocalWarningZoneBinding(
                zone_id=policy.sensor.disabled_zone_id,
                zone_type=ZoneType.DISABLED,
                led_actuator_id=DISABLED_ZONE_WARNING_LED_ID,
                led_action=BLINK_ACTION,
                speaker_actuator_id=(
                    DISABLED_ZONE_WARNING_SPEAKER_ID
                ),
                speaker_action=PLAY_ACTION,
            ),
            LocalWarningZoneBinding(
                zone_id=policy.sensor.ev_charging_zone_id,
                zone_type=ZoneType.EV_CHARGING,
                led_actuator_id=EV_ZONE_WARNING_LED_ID,
                led_action=BLINK_ACTION,
                speaker_actuator_id=EV_ZONE_WARNING_SPEAKER_ID,
                speaker_action=PLAY_ACTION,
            ),
        ),
        led_port=dependencies.led_port,
        speaker_port=dependencies.speaker_port,
    )

    authorization_query = RepositoryTofZoneAuthorizationQuery(
        projection_store=monitoring_projection_store,
    )
    authorization_service = TofZoneAuthorizationService(
        zones=zones,
        policy=policy.authorization,
        query=authorization_query,
    )

    def sensor_runtime_available() -> bool:
        return (
            sensor_worker.is_running
            and sensor_worker.failure is None
        )

    authorization_coordinator = TofZoneAuthorizationCoordinator(
        authorization_service=authorization_service,
        occupancy_snapshots=sensor_worker.snapshots,
        sensor_runtime_available=sensor_runtime_available,
        connection_factory=dependencies.connection_factory,
        assessment_consumer=(
            local_warning_coordinator.consume_assessment
        ),
    )
    authorization_worker = TofAuthorizationWorker(
        coordinator=authorization_coordinator,
        mailbox=mailbox,
        policy=policy.reevaluation,
    )

    return TofWarningRuntime(
        sensor_worker=sensor_worker,
        authorization_coordinator=authorization_coordinator,
        authorization_worker=authorization_worker,
        local_warning_coordinator=local_warning_coordinator,
        _mailbox=mailbox,
        _monitoring_projection_store=monitoring_projection_store,
    )
