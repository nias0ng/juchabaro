"""Jetson ToF 경고 production hardware와 Worker 생명주기를 관리한다.

Settings를 production adapter와 순수 TofWarningRuntime 구성으로 변환하고,
LED·speaker 초기화 실패를 장치별로 격리한다. Monitoring observer와 FastAPI
lifespan 연결, Incident·outbox·Backend 연동은 이 모듈의 책임이 아니다.

SensorArray의 open과 close는 SensorWorker가 소유한다. 이 owner는 SensorArray를
직접 열거나 닫지 않는다. lifecycle 메서드는 하나의 composition thread에서
직렬로 호출해야 한다.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Protocol, cast

from src.actuators.adapters.audio_backend import (
    AplayAudioBackend,
    AudioPlaybackBackend,
)
from src.actuators.adapters.jetson_gpio_led import (
    JetsonGpioLedAdapter,
)
from src.actuators.adapters.jetson_usb_speaker import (
    JetsonUsbSpeakerAdapter,
)
from src.actuators.models import ActuatorCommand
from src.actuators.ports import ActuatorPort
from src.application.sensor_factory import TofSensorRuntimePolicy
from src.application.sensor_worker import SensorWorker
from src.application.tof_authorization_worker import (
    TofAuthorizationWorker,
)
from src.application.tof_warning_runtime_factory import (
    TofWarningRuntime,
    TofWarningRuntimeDependencies,
    TofWarningRuntimePolicy,
    build_tof_warning_runtime,
)
from src.application.tof_zone_authorization import (
    TofAuthorizationPolicy,
)
from src.application.tof_zone_authorization_coordinator import (
    ConnectionFactory,
)
from src.config.settings import Settings
from src.parking.models import ZoneId
from src.parking.zone_registry import ZoneRegistry
from src.sensors.adapters.vl53l0x_array import Vl53l0xArray
from src.sensors.ports import SensorArray


logger = logging.getLogger(__name__)


_CORE_SETTING_NAMES = (
    "tof_i2c_bus",
    "tof_shutdown_settle_seconds",
    "tof_boot_settle_seconds",
    "tof_io_timeout_seconds",
    "tof_disabled_zone_id",
    "tof_ev_charging_zone_id",
    "tof_poll_interval_seconds",
    "tof_enter_distance_mm",
    "tof_exit_distance_mm",
    "tof_enter_confirm_seconds",
    "tof_exit_confirm_seconds",
    "tof_trusted_sample_max_gap_seconds",
    "tof_stale_after_seconds",
    "tof_occupancy_freshness_seconds",
    "tof_monitoring_freshness_seconds",
    "tof_max_pre_occupancy_observation_seconds",
)


class _LifecycleActuatorPort(ActuatorPort, Protocol):
    """Production actuator의 projection 및 open/close 경계."""

    def open(self) -> None:
        ...

    def close(self) -> None:
        ...


SensorArrayFactory = Callable[..., SensorArray]
ActuatorAdapterFactory = Callable[..., _LifecycleActuatorPort]
AudioBackendFactory = Callable[..., AudioPlaybackBackend]
ManagedWorker = SensorWorker | TofAuthorizationWorker


@dataclass(frozen=True, kw_only=True)
class TofWarningHardwareFactories:
    """실제 Jetson adapter 생성을 교체할 수 있는 최소 factory 경계."""

    sensor_array_factory: SensorArrayFactory = Vl53l0xArray
    led_adapter_factory: ActuatorAdapterFactory = JetsonGpioLedAdapter
    audio_backend_factory: AudioBackendFactory = AplayAudioBackend
    speaker_adapter_factory: ActuatorAdapterFactory = (
        JetsonUsbSpeakerAdapter
    )

    def __post_init__(self) -> None:
        for field_name in (
            "sensor_array_factory",
            "led_adapter_factory",
            "audio_backend_factory",
            "speaker_adapter_factory",
        ):
            if not callable(getattr(self, field_name)):
                raise ValueError(f"{field_name}는 callable이어야 합니다.")


@dataclass(frozen=True, kw_only=True)
class TofWarningRuntimeFailure:
    """격리된 production 구성 또는 lifecycle 실패."""

    component: str
    stage: str
    error: Exception


@dataclass(frozen=True, kw_only=True)
class _ResolvedCoreSettings:
    i2c_bus: int
    shutdown_settle_seconds: float
    boot_settle_seconds: float
    io_timeout_seconds: float

    disabled_zone_id: int
    ev_charging_zone_id: int
    poll_interval_seconds: float
    enter_distance_mm: float
    exit_distance_mm: float
    enter_confirm_seconds: float
    exit_confirm_seconds: float
    trusted_sample_max_gap_seconds: float
    stale_after_seconds: float

    occupancy_freshness_seconds: float
    monitoring_freshness_seconds: float
    max_pre_occupancy_observation_seconds: float


@dataclass(frozen=True, kw_only=True)
class _PortPreparationFailure:
    open_error: Exception
    rollback_error: Exception | None


class _IsolatedActuatorPort:
    """초기화 unavailable과 정상 open 이후 runtime failure를 구분한다."""

    def __init__(
        self,
        *,
        adapter: _LifecycleActuatorPort | None,
    ) -> None:
        self._adapter = adapter
        self._prepare_attempted = False
        self._available = False
        self._closed = False

    @property
    def available(self) -> bool:
        return self._available

    def prepare(self) -> _PortPreparationFailure | None:
        if self._closed:
            raise RuntimeError("closed actuator port cannot be prepared")
        if self._prepare_attempted:
            return None

        self._prepare_attempted = True
        adapter = self._adapter
        if adapter is None:
            return None

        try:
            adapter.open()
        except Exception as open_error:
            rollback_error: Exception | None = None
            try:
                # Adapter가 수행한 내부 rollback 이후 남은 cleanup 결과를
                # owner 경계에서도 확정한다.
                adapter.close()
            except Exception as error:
                rollback_error = error
            finally:
                self._available = False
                self._closed = True

            return _PortPreparationFailure(
                open_error=open_error,
                rollback_error=rollback_error,
            )

        self._available = True
        return None

    def apply_projection(
        self,
        commands: tuple[ActuatorCommand, ...],
    ) -> None:
        if not self._available:
            return

        adapter = self._adapter
        assert adapter is not None

        # 정상 open 이후 runtime failure는 LocalWarningCoordinator 또는
        # shutdown owner가 관찰해야 하므로 숨기지 않는다.
        adapter.apply_projection(commands)

    def close(self) -> None:
        if self._closed:
            return

        adapter = self._adapter
        try:
            if adapter is not None:
                adapter.close()
        finally:
            self._available = False
            self._closed = True


class JetsonTofWarningRuntime:
    """ToF production hardware 및 Worker lifecycle owner."""

    def __init__(
        self,
        *,
        runtime: TofWarningRuntime,
        led_port: _IsolatedActuatorPort,
        speaker_port: _IsolatedActuatorPort,
        initial_failures: tuple[TofWarningRuntimeFailure, ...] = (),
    ) -> None:
        self._runtime = runtime
        self._led_port = led_port
        self._speaker_port = speaker_port
        self._failures = list(initial_failures)

        self._prepared = False
        self._start_attempted = False
        self._workers_start_succeeded = False
        self._stop_requested = False

        # stop 호출 여부가 아니라 실제 thread 종료 관찰 결과다.
        self._sensor_worker_stopped = False
        self._authorization_worker_stopped = False

        self._closed = False

    @property
    def runtime(self) -> TofWarningRuntime:
        """순수 dependency wiring으로 구성된 ToF runtime."""

        return self._runtime

    @property
    def workers_started(self) -> bool:
        """두 Worker의 시작이 한 번 성공했는지 반환한다.

        이 값은 이력 상태다. 이후 background failure나 정상 stop으로 Worker가
        종료되어도 True를 유지한다.
        """

        return self._workers_start_succeeded

    @property
    def both_workers_running(self) -> bool:
        """Sensor와 authorization Worker가 모두 실행 중인지 반환한다.

        이 값은 정상 운영 상태를 확인하기 위한 값이다. cleanup 가능 여부는
        Worker 하나라도 실행 중인지 확인하는 close()의 OR 조건을 따라야 한다.
        """

        return (
            self._runtime.sensor_worker.is_running
            and self._runtime.authorization_worker.is_running
        )

    @property
    def failures(self) -> tuple[TofWarningRuntimeFailure, ...]:
        """지금까지 격리한 구성, startup, stop 및 cleanup 실패."""

        return tuple(self._failures)

    def prepare(self) -> None:
        """LED와 speaker를 독립적으로 준비한다.

        SensorArray는 열지 않고 Worker도 시작하지 않는다. 장치별 초기화 실패는
        해당 장치 unavailable 상태로 격리한다.
        """

        if self._closed:
            raise RuntimeError("closed ToF warning runtime cannot be prepared")
        if self._prepared:
            return

        self._prepare_port(
            component="led",
            port=self._led_port,
        )
        self._prepare_port(
            component="speaker",
            port=self._speaker_port,
        )
        self._prepared = True

    def start(self) -> None:
        """Authorization 이후 SensorWorker를 한 번만 시작한다."""

        if self._closed:
            raise RuntimeError("closed ToF warning runtime cannot be started")
        if not self._prepared:
            raise RuntimeError(
                "ToF warning runtime must be prepared before start"
            )
        if self._stop_requested:
            raise RuntimeError(
                "stopped ToF warning runtime cannot be restarted"
            )
        if self._start_attempted:
            raise RuntimeError(
                "ToF warning runtime may only be started once"
            )

        self._start_attempted = True
        authorization_worker = self._runtime.authorization_worker
        sensor_worker = self._runtime.sensor_worker

        try:
            authorization_worker.start()
        except Exception as error:
            self._authorization_worker_stopped = (
                not authorization_worker.is_running
            )
            self._sensor_worker_stopped = not sensor_worker.is_running
            self._record_failure(
                component="authorization_worker",
                stage="start",
                error=error,
            )
            logger.exception(
                "ToF authorization Worker 시작에 실패했습니다."
            )
            return

        try:
            sensor_worker.start()
        except Exception as error:
            self._sensor_worker_stopped = not sensor_worker.is_running
            self._record_failure(
                component="sensor_worker",
                stage="start",
                error=error,
            )
            logger.exception("ToF SensorWorker 시작에 실패했습니다.")

            try:
                authorization_worker.stop()
            except Exception as rollback_error:
                self._record_failure(
                    component="authorization_worker",
                    stage="startup_rollback",
                    error=rollback_error,
                )
                logger.exception(
                    "ToF sensor startup 실패 후 authorization Worker "
                    "정리에 실패했습니다."
                )
            finally:
                self._authorization_worker_stopped = (
                    not authorization_worker.is_running
                )
            return

        self._workers_start_succeeded = True
        self._sensor_worker_stopped = False
        self._authorization_worker_stopped = False
        logger.info("Jetson ToF 경고 Worker가 시작됐습니다.")

    def stop_workers(self) -> None:
        """Sensor 이후 authorization Worker를 best-effort로 중지한다.

        stop 오류 후 Worker가 계속 실행 중이면 완료 상태로 표시하지 않는다.
        다음 호출은 해당 Worker의 stop을 다시 시도한다. 이미 종료된 Worker는
        다시 호출하지 않는다.
        """

        self._stop_requested = True

        if not self._sensor_worker_stopped:
            self._sensor_worker_stopped = self._stop_worker(
                component="sensor_worker",
                worker=self._runtime.sensor_worker,
            )

        if not self._authorization_worker_stopped:
            self._authorization_worker_stopped = self._stop_worker(
                component="authorization_worker",
                worker=self._runtime.authorization_worker,
            )

    def close(self) -> None:
        """Worker 종료 확인 후 projection과 actuator를 정리한다."""

        if self._closed:
            return

        if (
            self._runtime.sensor_worker.is_running
            or self._runtime.authorization_worker.is_running
        ):
            raise RuntimeError(
                "ToF warning Workers must be stopped before close"
            )

        cleanup_steps = (
            (
                "speaker",
                "projection_clear",
                lambda: self._speaker_port.apply_projection(()),
            ),
            (
                "led",
                "projection_clear",
                lambda: self._led_port.apply_projection(()),
            ),
            ("speaker", "close", self._speaker_port.close),
            ("led", "close", self._led_port.close),
        )

        try:
            for component, stage, cleanup in cleanup_steps:
                try:
                    cleanup()
                except Exception as error:
                    self._record_failure(
                        component=component,
                        stage=stage,
                        error=error,
                    )
                    logger.exception(
                        "ToF 경고 장치 정리에 실패했습니다. "
                        "component=%s stage=%s",
                        component,
                        stage,
                    )
        finally:
            self._closed = True

    def _stop_worker(
        self,
        *,
        component: str,
        worker: ManagedWorker,
    ) -> bool:
        stop_error: Exception | None = None

        try:
            worker.stop()
        except Exception as error:
            stop_error = error
            self._record_failure(
                component=component,
                stage="stop",
                error=error,
            )
            logger.exception("%s 종료에 실패했습니다.", component)

        if not worker.is_running:
            return True

        # stop이 예외 없이 반환했더라도 thread가 남았다면 완료로 볼 수 없다.
        if stop_error is None:
            incomplete_error = RuntimeError(
                f"{component} remained running after stop"
            )
            self._record_failure(
                component=component,
                stage="stop_incomplete",
                error=incomplete_error,
            )
            logger.error(
                "%s stop 이후에도 Worker가 실행 중입니다.",
                component,
            )

        return False

    def _prepare_port(
        self,
        *,
        component: str,
        port: _IsolatedActuatorPort,
    ) -> None:
        failure = port.prepare()
        if failure is None:
            return

        self._record_failure(
            component=component,
            stage="open",
            error=failure.open_error,
        )
        logger.error(
            "ToF 경고 장치 초기화에 실패했습니다. component=%s",
            component,
            exc_info=(
                type(failure.open_error),
                failure.open_error,
                failure.open_error.__traceback__,
            ),
        )

        if failure.rollback_error is None:
            return

        self._record_failure(
            component=component,
            stage="open_rollback",
            error=failure.rollback_error,
        )
        logger.error(
            "ToF 경고 장치 초기화 rollback에 실패했습니다. "
            "component=%s",
            component,
            exc_info=(
                type(failure.rollback_error),
                failure.rollback_error,
                failure.rollback_error.__traceback__,
            ),
        )

    def _record_failure(
        self,
        *,
        component: str,
        stage: str,
        error: Exception,
    ) -> None:
        self._failures.append(
            TofWarningRuntimeFailure(
                component=component,
                stage=stage,
                error=error,
            )
        )


def build_jetson_tof_warning_runtime(
    *,
    settings: Settings,
    zones: ZoneRegistry,
    connection_factory: ConnectionFactory,
    factories: TofWarningHardwareFactories | None = None,
) -> JetsonTofWarningRuntime | None:
    """Settings로 시작하지 않은 production ToF runtime을 구성한다.

    함수 호출만으로 장치를 open하거나 Worker를 시작하거나 DB connection을
    생성하지 않는다. core 설정 오류는 ToF runtime만 비활성화한다.
    """

    if not settings.tof_enabled:
        return None

    core = _resolve_core_settings(settings)
    if core is None:
        return None

    active_factories = (
        TofWarningHardwareFactories()
        if factories is None
        else factories
    )

    try:
        sensor_array = active_factories.sensor_array_factory(
            i2c_bus=core.i2c_bus,
            shutdown_settle_seconds=core.shutdown_settle_seconds,
            boot_settle_seconds=core.boot_settle_seconds,
            io_timeout_seconds=core.io_timeout_seconds,
        )
        sensor_policy = TofSensorRuntimePolicy(
            disabled_zone_id=ZoneId(core.disabled_zone_id),
            ev_charging_zone_id=ZoneId(core.ev_charging_zone_id),
            poll_interval_seconds=core.poll_interval_seconds,
            enter_distance_mm=core.enter_distance_mm,
            exit_distance_mm=core.exit_distance_mm,
            enter_confirm_seconds=core.enter_confirm_seconds,
            exit_confirm_seconds=core.exit_confirm_seconds,
            trusted_sample_max_gap_seconds=(
                core.trusted_sample_max_gap_seconds
            ),
            stale_after_seconds=core.stale_after_seconds,
        )
        authorization_policy = TofAuthorizationPolicy(
            occupancy_freshness_seconds=(
                core.occupancy_freshness_seconds
            ),
            monitoring_freshness_seconds=(
                core.monitoring_freshness_seconds
            ),
            max_pre_occupancy_observation_seconds=(
                core.max_pre_occupancy_observation_seconds
            ),
        )
    except Exception:
        logger.exception(
            "ToF core 설정 또는 SensorArray 구성 의미 검증에 실패해 "
            "runtime을 비활성화합니다."
        )
        return None

    initial_failures: list[TofWarningRuntimeFailure] = []

    led_adapter: _LifecycleActuatorPort | None
    try:
        led_adapter = active_factories.led_adapter_factory()
    except Exception as error:
        led_adapter = None
        initial_failures.append(
            TofWarningRuntimeFailure(
                component="led",
                stage="construction",
                error=error,
            )
        )
        logger.exception(
            "ToF 경고 LED adapter 생성에 실패해 LED를 비활성화합니다."
        )

    speaker_adapter, speaker_failures = _build_speaker_adapter(
        settings=settings,
        factories=active_factories,
    )
    initial_failures.extend(speaker_failures)

    led_port = _IsolatedActuatorPort(adapter=led_adapter)
    speaker_port = _IsolatedActuatorPort(adapter=speaker_adapter)

    try:
        runtime = build_tof_warning_runtime(
            zones=zones,
            policy=TofWarningRuntimePolicy(
                sensor=sensor_policy,
                authorization=authorization_policy,
            ),
            dependencies=TofWarningRuntimeDependencies(
                sensor_array=sensor_array,
                led_port=led_port,
                speaker_port=speaker_port,
                connection_factory=connection_factory,
            ),
        )
    except Exception:
        logger.exception(
            "ToF core runtime 의미 검증에 실패해 runtime을 "
            "비활성화합니다."
        )
        return None

    return JetsonTofWarningRuntime(
        runtime=runtime,
        led_port=led_port,
        speaker_port=speaker_port,
        initial_failures=tuple(initial_failures),
    )


def _resolve_core_settings(
    settings: Settings,
) -> _ResolvedCoreSettings | None:
    missing = tuple(
        name
        for name in _CORE_SETTING_NAMES
        if getattr(settings, name) is None
    )
    if missing:
        logger.error(
            "ToF core 설정이 누락되어 runtime을 비활성화합니다. "
            "missing=%s",
            ",".join(missing),
        )
        return None

    return _ResolvedCoreSettings(
        i2c_bus=cast(int, settings.tof_i2c_bus),
        shutdown_settle_seconds=cast(
            float,
            settings.tof_shutdown_settle_seconds,
        ),
        boot_settle_seconds=cast(
            float,
            settings.tof_boot_settle_seconds,
        ),
        io_timeout_seconds=cast(
            float,
            settings.tof_io_timeout_seconds,
        ),
        disabled_zone_id=cast(int, settings.tof_disabled_zone_id),
        ev_charging_zone_id=cast(
            int,
            settings.tof_ev_charging_zone_id,
        ),
        poll_interval_seconds=cast(
            float,
            settings.tof_poll_interval_seconds,
        ),
        enter_distance_mm=cast(
            float,
            settings.tof_enter_distance_mm,
        ),
        exit_distance_mm=cast(
            float,
            settings.tof_exit_distance_mm,
        ),
        enter_confirm_seconds=cast(
            float,
            settings.tof_enter_confirm_seconds,
        ),
        exit_confirm_seconds=cast(
            float,
            settings.tof_exit_confirm_seconds,
        ),
        trusted_sample_max_gap_seconds=cast(
            float,
            settings.tof_trusted_sample_max_gap_seconds,
        ),
        stale_after_seconds=cast(
            float,
            settings.tof_stale_after_seconds,
        ),
        occupancy_freshness_seconds=cast(
            float,
            settings.tof_occupancy_freshness_seconds,
        ),
        monitoring_freshness_seconds=cast(
            float,
            settings.tof_monitoring_freshness_seconds,
        ),
        max_pre_occupancy_observation_seconds=cast(
            float,
            settings.tof_max_pre_occupancy_observation_seconds,
        ),
    )


def _build_speaker_adapter(
    *,
    settings: Settings,
    factories: TofWarningHardwareFactories,
) -> tuple[
    _LifecycleActuatorPort | None,
    tuple[TofWarningRuntimeFailure, ...],
]:
    values = (
        settings.tof_disabled_zone_warning_wav_path,
        settings.tof_ev_zone_warning_wav_path,
        settings.tof_warning_audio_device,
    )
    provided_count = sum(value is not None for value in values)

    if provided_count == 0:
        logger.info(
            "ToF speaker 설정이 없어 local speaker를 비활성화합니다."
        )
        return None, ()

    if provided_count != len(values):
        error = ValueError(
            "ToF speaker 설정은 WAV path 2개와 audio device를 "
            "모두 제공해야 합니다."
        )
        logger.error(
            "ToF speaker 설정이 부분적으로만 제공되어 speaker를 "
            "비활성화합니다."
        )
        return (
            None,
            (
                TofWarningRuntimeFailure(
                    component="speaker",
                    stage="configuration",
                    error=error,
                ),
            ),
        )

    disabled_wav_path = cast(
        Path,
        settings.tof_disabled_zone_warning_wav_path,
    )
    ev_wav_path = cast(
        Path,
        settings.tof_ev_zone_warning_wav_path,
    )
    audio_device = cast(str, settings.tof_warning_audio_device)

    backend: AudioPlaybackBackend | None = None
    try:
        backend = factories.audio_backend_factory(
            device=audio_device,
        )
        adapter = factories.speaker_adapter_factory(
            backend=backend,
            disabled_zone_warning_wav_path=disabled_wav_path,
            ev_zone_warning_wav_path=ev_wav_path,
        )
    except Exception as error:
        failures = [
            TofWarningRuntimeFailure(
                component="speaker",
                stage="construction",
                error=error,
            )
        ]
        logger.exception(
            "ToF speaker adapter 생성에 실패해 speaker를 "
            "비활성화합니다."
        )

        if backend is not None:
            try:
                backend.close()
            except Exception as cleanup_error:
                failures.append(
                    TofWarningRuntimeFailure(
                        component="speaker",
                        stage="construction_rollback",
                        error=cleanup_error,
                    )
                )
                logger.exception(
                    "ToF speaker 생성 실패 후 audio backend 정리에 "
                    "실패했습니다."
                )

        return None, tuple(failures)

    return adapter, ()
