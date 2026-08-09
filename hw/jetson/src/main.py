"""Jetson FastAPI application composition root.

DB, zones, evidence, publication, monitoring 및 ToF warning lifecycle을 하나의
lifespan에서 소유한다. module-level ``src.main:app``은 운영 monitoring과
ToF concrete factory를 모두 결속한다.

일반 ``create_app()``은 두 hardware factory를 생략할 수 있다. ToF factory를
생략하면 실제 ToF hardware는 생성되지 않는다. ToF 구성·시작·종료 실패는
Monitoring startup과 격리하며, shutdown에서는 ToF Worker를 먼저 중지한 뒤
actuator를 정리한다.
"""

from __future__ import annotations

import logging
import sqlite3
import sys
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypeAlias

from fastapi import FastAPI

from src.api.error_handlers import register_error_handlers
from src.api.entry_events_router import router as entry_events_router
from src.api.health_router import router as health_router
from src.api.internal_commands_router import router as internal_commands_router
from src.api.live_stream_router import router as live_stream_router
from src.application.entry_event_intake import EntryEventIntake
from src.application.entry_review_resolution_intake import (
    EntryReviewResolutionIntake,
)
from src.application.evidence_publication_worker import (
    EvidencePublicationPublisher,
    EvidencePublicationWorker,
)
from src.application.monitoring_factory import (
    MonitoringDependencies,
    build_monitoring_pipeline,
)
from src.application.monitoring_pipeline import (
    FrameObserver,
    MonitoringPipeline,
)
from src.application.monitoring_worker import MonitoringWorker
from src.application.move_verification_executor import (
    MoveVerificationExecutor,
    MoveVerificationExecutorWorker,
)
from src.application.move_verification_intake import MoveVerificationIntake
from src.application.outbox_publisher import (
    OutboxPublisher,
    OutboxPublisherWorker,
)
from src.application.session_context_update_intake import (
    SessionContextUpdateIntake,
)
from src.application.tof_monitoring_context_observer import (
    TofMonitoringContextObserver,
    TofMonitoringContextObserverPolicy,
    compose_frame_observers,
)
from src.camera.calibration_utils import load_calibration
from src.camera.frame_source import (
    OpenCvWebcamFrameSource,
    RemapFrameSource,
    calibration_fingerprint,
)
from src.communication.backend_client import BackendClient
from src.communication.backend_publication_preparer import (
    BackendPublicationPreparer,
)
from src.config.monitoring_policy import (
    build_monitoring_policy as _build_monitoring_policy,
)
from src.config.settings import Settings, get_settings
from src.diagnostics import DiagnosticsSink, LoggingDiagnosticsAdapter
from src.evidence.capture import EvidenceCaptureCoordinator
from src.live.overlay_publisher import OverlayPublisher
from src.parking.egress_aisle_registry import EgressAisleRegistry
from src.parking.models import ZoneId
from src.parking.zone_registry import ZoneRegistry
from src.session.context_binding_coordinator import ContextBindingCoordinator
from src.session.entry_match_coordinator import EntryMatchCoordinator
from src.storage.database import connect_database, open_database
from src.storage.publication_runtime_lock import PublicationRuntimeLock
from src.tracking.adapters.side_masking_detector import (
    SideMaskingDetector,
    compute_mask_ratios_from_zones,
)
from src.tracking.adapters.ultralytics_bytetrack import (
    UltralyticsVehicleTracker,
)
from src.tracking.model_manifest import validate_vehicle_model_assets
from src.tof_warning_production_runtime import (
    JetsonTofWarningRuntime,
    build_jetson_tof_warning_runtime,
)


logger = logging.getLogger(__name__)


DatabaseConnectionFactory = Callable[[], sqlite3.Connection]
ShutdownWorker: TypeAlias = (
    MonitoringWorker
    | MoveVerificationExecutorWorker
    | OutboxPublisherWorker
    | EvidencePublicationWorker
)


def _stop_workers_best_effort(
    workers: tuple[tuple[str, ShutdownWorker | None], ...],
    *,
    suppress_errors: bool,
) -> None:
    """모든 worker 정리를 시도하고 정상 종료에서는 첫 오류를 전파한다."""

    first_error: Exception | None = None
    for name, worker in workers:
        if worker is None:
            continue
        try:
            worker.stop()
        except Exception as error:
            if first_error is None:
                first_error = error
            logger.exception("%s worker 종료에 실패했습니다.", name)

    if first_error is not None and not suppress_errors:
        raise first_error


@dataclass(frozen=True)
class RuntimeContext:
    """확정된 기동 설정·구역·DB·outbound wire adapter 경계."""

    settings: Settings
    zones: ZoneRegistry
    egress_aisles: EgressAisleRegistry
    connection_factory: DatabaseConnectionFactory
    publication_preparer: BackendPublicationPreparer
    evidence_capture_coordinator: EvidenceCaptureCoordinator
    diagnostics_sink: DiagnosticsSink | None = None


MonitoringPipelineFactory = Callable[[RuntimeContext], MonitoringPipeline]


class TofWarningRuntimeFactory(Protocol):
    """Settings와 production port로 시작 전 ToF owner를 구성한다."""

    def __call__(
        self,
        *,
        settings: Settings,
        zones: ZoneRegistry,
        connection_factory: DatabaseConnectionFactory,
    ) -> JetsonTofWarningRuntime | None:
        ...


def _build_tof_runtime_best_effort(
    *,
    settings: Settings,
    zones: ZoneRegistry,
    connection_factory: DatabaseConnectionFactory,
    factory: TofWarningRuntimeFactory | None,
) -> JetsonTofWarningRuntime | None:
    if factory is None:
        if settings.tof_enabled:
            logger.warning(
                "TOF_ENABLED=true이지만 production factory가 없어 "
                "ToF runtime을 비활성화합니다. "
                "component=tof_warning_runtime stage=construction"
            )
        return None

    try:
        return factory(
            settings=settings,
            zones=zones,
            connection_factory=connection_factory,
        )
    except Exception:
        logger.exception(
            "ToF 경고 runtime 구성에 실패해 비활성화합니다. "
            "component=tof_warning_runtime stage=construction"
        )
        return None


def _build_tof_monitoring_observer_best_effort(
    *,
    settings: Settings,
    runtime: JetsonTofWarningRuntime | None,
) -> TofMonitoringContextObserver | None:
    if runtime is None:
        return None

    try:
        disabled_zone_id = settings.tof_disabled_zone_id
        ev_charging_zone_id = settings.tof_ev_charging_zone_id
        monitoring_freshness_seconds = (
            settings.tof_monitoring_freshness_seconds
        )
        if (
            disabled_zone_id is None
            or ev_charging_zone_id is None
            or monitoring_freshness_seconds is None
        ):
            raise ValueError(
                "ToF monitoring observer 설정이 완전하지 않습니다."
            )

        return TofMonitoringContextObserver(
            requester=runtime.runtime,
            policy=TofMonitoringContextObserverPolicy(
                target_zone_ids=(
                    ZoneId(disabled_zone_id),
                    ZoneId(ev_charging_zone_id),
                ),
                monitoring_freshness_seconds=(
                    monitoring_freshness_seconds
                ),
            ),
        )
    except Exception:
        logger.exception(
            "ToF monitoring observer 구성에 실패해 frame 재평가 "
            "신호를 비활성화합니다. "
            "component=tof_monitoring_context_observer "
            "stage=construction"
        )
        return None


def _compose_monitoring_observers_best_effort(
    *,
    overlay_publisher: OverlayPublisher | None,
    tof_observer: TofMonitoringContextObserver | None,
) -> tuple[
    FrameObserver | None,
    TofMonitoringContextObserver | None,
]:
    try:
        return (
            compose_frame_observers(
                overlay_publisher,
                tof_observer,
            ),
            tof_observer,
        )
    except Exception:
        logger.exception(
            "Monitoring observer 합성에 실패해 기존 overlay만 "
            "유지합니다. "
            "component=tof_monitoring_context_observer "
            "stage=composition"
        )
        return overlay_publisher, None


def _prepare_tof_runtime_best_effort(
    runtime: JetsonTofWarningRuntime | None,
) -> bool:
    if runtime is None:
        return False

    try:
        runtime.prepare()
    except Exception:
        logger.exception(
            "ToF 경고 runtime prepare에 실패했습니다. "
            "component=tof_warning_runtime stage=prepare"
        )
        return False
    return True


def _start_tof_runtime_best_effort(
    runtime: JetsonTofWarningRuntime | None,
) -> None:
    if runtime is None:
        return

    try:
        runtime.start()
    except Exception:
        logger.exception(
            "ToF 경고 runtime start에 실패했습니다. "
            "component=tof_warning_runtime stage=start"
        )


def _run_tof_cleanup_step(
    *,
    runtime: JetsonTofWarningRuntime | None,
    stage: str,
    operation: Callable[[JetsonTofWarningRuntime], None],
) -> Exception | None:
    if runtime is None:
        return None

    try:
        operation(runtime)
    except Exception as error:
        logger.exception(
            "ToF 경고 runtime cleanup에 실패했습니다. "
            "component=tof_warning_runtime stage=%s",
            stage,
        )
        return error
    return None


def _validate_monitoring_assets(
    settings: Settings,
    zones: ZoneRegistry,
) -> None:
    """운영 camera·model asset을 장치 객체 생성 전에 검증한다."""

    if not settings.calibration_path.is_file():
        raise ValueError(
            "calibration_path가 실제 calibration 파일이 아닙니다: "
            f"{settings.calibration_path}"
        )

    # K/D/image_size와 fisheye calibration JSON 계약을 기존 parser로 검증한다.
    load_calibration(str(settings.calibration_path))

    calibration_sha = calibration_fingerprint(
        settings.calibration_path,
        settings.remap_balance,
    )["calibrationSha256"]
    if calibration_sha != zones.calibration_reference:
        raise ValueError(
            "calibration 파일 SHA가 ZoneRegistry.calibration_reference와 "
            "일치하지 않습니다: "
            f"calibrationSha256={calibration_sha}, "
            f"calibrationReference={zones.calibration_reference}"
        )

    # 파일명이 같은 stock COCO model을 오배치해도 장치 객체를
    # 만들기 전에 fail-closed로 중단한다.
    validate_vehicle_model_assets(
        model_path=settings.vehicle_model_path,
        manifest_path=settings.vehicle_model_manifest_path,
    )


def build_runtime_monitoring_pipeline(
    context: RuntimeContext,
) -> MonitoringPipeline:
    """운영 Settings와 RuntimeContext로 camera·tracking pipeline을 조립한다."""

    settings = context.settings
    _validate_monitoring_assets(settings, context.zones)

    webcam = OpenCvWebcamFrameSource(
        camera_id=settings.camera_id,
        camera_index=settings.camera_index,
        width=settings.camera_width,
        height=settings.camera_height,
        fourcc=settings.camera_fourcc,
        fps=settings.camera_fps,
    )
    frame_source = RemapFrameSource(
        inner=webcam,
        calibration_path=str(settings.calibration_path),
        balance=settings.remap_balance,
        backend=settings.remap_backend,
    )

    tracker = UltralyticsVehicleTracker(
        model_path=str(settings.vehicle_model_path),
        tracker_config=settings.vehicle_tracker_config,
        confidence=settings.vehicle_tracking_confidence,
    )
    left_ratio, right_ratio = compute_mask_ratios_from_zones(
        context.zones.all(),
        margin_ratio=settings.mask_margin_ratio,
    )
    detector = SideMaskingDetector(
        inner=tracker,
        left_mask_end_ratio=left_ratio,
        right_mask_start_ratio=right_ratio,
    )

    dependencies = MonitoringDependencies(
        camera_id=settings.camera_id,
        frame_source=frame_source,
        detector=detector,
        publication_preparer=context.publication_preparer,
        connection_factory=context.connection_factory,
        evidence_capture_sink=context.evidence_capture_coordinator,
        diagnostics_sink=(
            context.diagnostics_sink or LoggingDiagnosticsAdapter()
        ),
        startup_warm_up=True,
    )
    return build_monitoring_pipeline(
        zones=context.zones,
        egress_aisles=context.egress_aisles,
        policy=_build_monitoring_policy(settings),
        dependencies=dependencies,
    )


def configure_logging() -> None:
    settings = get_settings()

    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def create_app(
    *,
    settings: Settings | None = None,
    monitoring_pipeline_factory: MonitoringPipelineFactory | None = None,
    tof_warning_runtime_factory: TofWarningRuntimeFactory | None = None,
) -> FastAPI:
    """FastAPI app을 만들고 process-local 자원 생명주기를 소유한다.

    module-level app은 monitoring과 ToF production factory를 모두 전달한다.
    직접 호출하는 API-only 테스트는 두 factory를 생략하거나 test double을
    주입할 수 있다. ToF factory가 없으면 실제 ToF hardware를 생성하지 않는다.
    ToF lifecycle 오류는 Monitoring startup과 격리하고, shutdown에서는 ToF
    Worker를 actuator보다 먼저 중지한다.
    """

    resolved_settings = settings or get_settings()

    def connection_factory() -> sqlite3.Connection:
        # FastAPI sync handler와 monitoring thread가 SQLite connection을
        # 공유하지 않도록 호출마다 새로 연다.
        return connect_database(resolved_settings.database_path)

    @asynccontextmanager
    async def runtime_lifespan(application: FastAPI):
        """Migration 후 application을 조립하고 종료 시 worker를 회수한다."""

        _prepare_database_path(resolved_settings.database_path)
        connection = open_database(resolved_settings.database_path)
        connection.close()
        zones = ZoneRegistry.from_file(
            resolved_settings.zone_definition_path
        )
        egress_aisles = EgressAisleRegistry.from_file(
            resolved_settings.egress_aisle_path,
            zones=zones,
        )
        entry_match_coordinator = EntryMatchCoordinator(zones=zones)
        application.state.zone_registry = zones
        application.state.egress_aisle_registry = egress_aisles
        application.state.entry_match_coordinator = entry_match_coordinator
        application.state.database_connection_factory = connection_factory
        application.state.tof_warning_runtime = None
        application.state.tof_monitoring_context_observer = None

        publication_preparer = BackendPublicationPreparer()
        application.state.publication_preparer = publication_preparer
        diagnostics_sink = LoggingDiagnosticsAdapter()
        evidence_capture_coordinator = EvidenceCaptureCoordinator(
            connection_factory=connection_factory,
            zones=zones,
            spool_path=resolved_settings.evidence_spool_path,
            spool_cap_bytes=resolved_settings.evidence_spool_cap_bytes,
            filesystem_floor_ratio=(
                resolved_settings.evidence_filesystem_floor_ratio
            ),
            capture_stop_free_ratio=(
                resolved_settings.evidence_capture_stop_free_ratio
            ),
            diagnostics_sink=diagnostics_sink,
        )
        application.state.evidence_capture_coordinator = (
            evidence_capture_coordinator
        )

        overlay_publisher: OverlayPublisher | None = None
        if resolved_settings.live_stream_enabled:
            overlay_publisher = OverlayPublisher(
                zones=zones,
                jpeg_quality=resolved_settings.live_stream_jpeg_quality,
                target_fps=resolved_settings.live_stream_target_fps,
            )
        application.state.overlay_publisher = overlay_publisher

        # 핵심 MonitoringPipeline을 optional ToF subsystem보다 먼저
        # 구성한다. 이 단계가 실패하면 아직 ToF owner는 존재하지 않는다.
        pipeline: MonitoringPipeline | None = None
        if monitoring_pipeline_factory is not None:
            pipeline = monitoring_pipeline_factory(
                RuntimeContext(
                    settings=resolved_settings,
                    zones=zones,
                    egress_aisles=egress_aisles,
                    connection_factory=connection_factory,
                    publication_preparer=publication_preparer,
                    evidence_capture_coordinator=(
                        evidence_capture_coordinator
                    ),
                    diagnostics_sink=diagnostics_sink,
                )
            )
            if (
                isinstance(pipeline, MonitoringPipeline)
                and not pipeline.has_evidence_capture_sink
            ):
                pipeline.bind_evidence_capture_sink(
                    evidence_capture_coordinator
                )

        tof_warning_runtime = _build_tof_runtime_best_effort(
            settings=resolved_settings,
            zones=zones,
            connection_factory=connection_factory,
            factory=tof_warning_runtime_factory,
        )
        application.state.tof_warning_runtime = tof_warning_runtime

        monitoring_worker: MonitoringWorker | None = None
        move_verification_worker: (
            MoveVerificationExecutorWorker | None
        ) = None
        evidence_publication_worker: EvidencePublicationWorker | None = None
        outbox_publisher_worker: OutboxPublisherWorker | None = None

        # ToF owner 생성 이후 발생하는 모든 composition/startup 오류는
        # 아래 finally에서 owner cleanup 대상이 된다.
        try:
            tof_runtime = (
                None
                if tof_warning_runtime is None
                else tof_warning_runtime.runtime
            )
            reevaluation_callback = (
                None
                if tof_runtime is None
                else (
                    tof_runtime
                    .request_after_monitoring_context_change
                )
            )

            application.state.entry_event_intake = EntryEventIntake(
                entry_match_coordinator,
                match_window_seconds=(
                    resolved_settings.entry_match_window_seconds
                ),
            )
            application.state.entry_review_resolution_intake = (
                EntryReviewResolutionIntake(
                    entry_match_coordinator,
                    after_applied=reevaluation_callback,
                )
            )
            application.state.session_context_update_intake = (
                SessionContextUpdateIntake(
                    ContextBindingCoordinator(),
                    after_applied=reevaluation_callback,
                )
            )
            application.state.move_verification_intake = (
                MoveVerificationIntake()
            )

            tof_monitoring_context_observer = (
                None
                if pipeline is None
                else _build_tof_monitoring_observer_best_effort(
                    settings=resolved_settings,
                    runtime=tof_warning_runtime,
                )
            )
            monitoring_frame_observer, active_tof_observer = (
                _compose_monitoring_observers_best_effort(
                    overlay_publisher=overlay_publisher,
                    tof_observer=tof_monitoring_context_observer,
                )
            )
            application.state.tof_monitoring_context_observer = (
                active_tof_observer
            )

            if pipeline is not None:
                monitoring_worker = MonitoringWorker(
                    pipeline,
                    frame_observer=monitoring_frame_observer,
                )
            application.state.monitoring_worker = monitoring_worker

            move_verification_worker = (
                MoveVerificationExecutorWorker(
                    MoveVerificationExecutor(
                        connection_factory=connection_factory,
                        publication_preparer=publication_preparer,
                    )
                )
            )
            application.state.move_verification_worker = (
                move_verification_worker
            )

            if resolved_settings.backend_hw_api_key.strip():
                evidence_publication_worker = (
                    EvidencePublicationWorker(
                        EvidencePublicationPublisher(
                            connection_factory=connection_factory,
                            client=BackendClient(
                                base_url=(
                                    resolved_settings.backend_base_url
                                ),
                                hw_api_key=(
                                    resolved_settings.backend_hw_api_key
                                ),
                            ),
                            spool_path=(
                                resolved_settings.evidence_spool_path
                            ),
                            spool_cap_bytes=(
                                resolved_settings
                                .evidence_spool_cap_bytes
                            ),
                            filesystem_floor_ratio=(
                                resolved_settings
                                .evidence_filesystem_floor_ratio
                            ),
                            capture_stop_free_ratio=(
                                resolved_settings
                                .evidence_capture_stop_free_ratio
                            ),
                            diagnostics_sink=diagnostics_sink,
                        )
                    )
                )
                outbox_publisher_worker = OutboxPublisherWorker(
                    OutboxPublisher(
                        connection_factory=connection_factory,
                        client=BackendClient(
                            base_url=resolved_settings.backend_base_url,
                            hw_api_key=(
                                resolved_settings.backend_hw_api_key
                            ),
                        ),
                    )
                )
            else:
                logger.warning(
                    "BACKEND_HW_API_KEY가 비어 Backend publication "
                    "worker를 비활성화합니다."
                )

            application.state.evidence_publication_worker = (
                evidence_publication_worker
            )
            application.state.outbox_publisher_worker = (
                outbox_publisher_worker
            )

            # Local recovery는 external publication·신규 frame보다 먼저
            # 완료한다. 그 뒤 parent Incident outbox, child Evidence
            # publisher, frame producer 순서로 허용한다.
            if evidence_publication_worker is not None:
                evidence_publication_worker.prepare()
            else:
                # Backend key가 없어 publisher를 끈 현장도 interrupted local
                # JPEG를 다음 capture 전 일관된 FAILED/READY 상태로 만든다.
                evidence_capture_coordinator.recover()

            tof_prepared = _prepare_tof_runtime_best_effort(
                tof_warning_runtime
            )

            if monitoring_worker is not None:
                monitoring_worker.prepare()
            if outbox_publisher_worker is not None:
                outbox_publisher_worker.start()
            if evidence_publication_worker is not None:
                evidence_publication_worker.start()
            if monitoring_worker is not None:
                monitoring_worker.start()
            move_verification_worker.start()

            if tof_prepared:
                _start_tof_runtime_best_effort(
                    tof_warning_runtime
                )

            if outbox_publisher_worker is not None:
                logger.info("Backend publication workers가 시작됐습니다.")
            yield
        finally:
            active_error = sys.exc_info()[1]
            tof_cleanup_error: Exception | None = None
            worker_cleanup_error: Exception | None = None

            initial_stop_error = _run_tof_cleanup_step(
                runtime=tof_warning_runtime,
                stage="stop_workers_initial",
                operation=lambda runtime: runtime.stop_workers(),
            )
            if initial_stop_error is not None:
                tof_cleanup_error = initial_stop_error

            try:
                _stop_workers_best_effort(
                    (
                        ("monitoring", monitoring_worker),
                        (
                            "move verification",
                            move_verification_worker,
                        ),
                        (
                            "outbox publication",
                            outbox_publisher_worker,
                        ),
                        (
                            "evidence publication",
                            evidence_publication_worker,
                        ),
                    ),
                    suppress_errors=active_error is not None,
                )
            except Exception as error:
                worker_cleanup_error = error

            final_stop_error = _run_tof_cleanup_step(
                runtime=tof_warning_runtime,
                stage="stop_workers_final",
                operation=lambda runtime: runtime.stop_workers(),
            )
            if (
                tof_cleanup_error is None
                and final_stop_error is not None
            ):
                tof_cleanup_error = final_stop_error

            close_error = _run_tof_cleanup_step(
                runtime=tof_warning_runtime,
                stage="close",
                operation=lambda runtime: runtime.close(),
            )
            if tof_cleanup_error is None and close_error is not None:
                tof_cleanup_error = close_error

            if active_error is None:
                if worker_cleanup_error is not None:
                    raise worker_cleanup_error
                if tof_cleanup_error is not None:
                    raise tof_cleanup_error

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        publication_runtime_lock = PublicationRuntimeLock(
            _publication_runtime_lock_path(resolved_settings)
        )
        application.state.publication_runtime_lock = publication_runtime_lock
        publication_runtime_lock.acquire()
        try:
            async with runtime_lifespan(application):
                yield
        finally:
            publication_runtime_lock.release()

    application = FastAPI(
        title=resolved_settings.app_name,
        version="0.1.0",
        description="Smart Parking Jetson hardware interface",
        lifespan=lifespan,
    )
    register_error_handlers(application)

    application.include_router(health_router)
    application.include_router(entry_events_router)
    application.include_router(internal_commands_router)
    application.include_router(live_stream_router)

    return application


def _create_runtime_app() -> FastAPI:
    """운영 monitoring과 ToF factory가 결속된 ASGI app을 생성한다."""

    return create_app(
        monitoring_pipeline_factory=build_runtime_monitoring_pipeline,
        tof_warning_runtime_factory=(
            build_jetson_tof_warning_runtime
        ),
    )


def _prepare_database_path(database_path: Path) -> None:
    """File DB의 부모 디렉터리만 기동 시 준비한다."""

    if str(database_path) != ":memory:":
        database_path.parent.mkdir(parents=True, exist_ok=True)


def _publication_runtime_lock_path(settings: Settings) -> Path:
    """DB file 단위의 process lock 경로를 결정한다."""

    if str(settings.database_path) == ":memory:":
        return (
            settings.evidence_spool_path.parent
            / f".{settings.evidence_spool_path.name}.publication.lock"
        )
    database_path = settings.database_path.resolve(strict=False)
    return database_path.with_name(
        f".{database_path.name}.publication.lock"
    )


configure_logging()
app = _create_runtime_app()
