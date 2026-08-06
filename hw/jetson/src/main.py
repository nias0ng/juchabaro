"""Jetson FastAPI application composition root.

DB, zones, evidence, publication, monitoring lifecycle을 하나의 lifespan에서
소유한다. module-level ``src.main:app``은 운영 camera·tracking factory와
정확한 Backend publication wire를 결속해 단일 MonitoringWorker를 기동한다.

``create_app()``의 optional factory 경계는 API-only 테스트와 명시적
dependency injection을 위해 유지하며, 운영 경로에 임시 serializer나
no-op publisher가 섞이지 않도록 한다.
"""

from __future__ import annotations

import logging
import sqlite3
import sys
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

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
from src.application.monitoring_pipeline import MonitoringPipeline
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
from src.parking.zone_registry import ZoneRegistry
from src.session.context_binding_coordinator import ContextBindingCoordinator
from src.session.entry_match_coordinator import EntryMatchCoordinator
from src.storage.database import connect_database, open_database
from src.tracking.adapters.side_masking_detector import (
    SideMaskingDetector,
    compute_mask_ratios_from_zones,
)
from src.tracking.adapters.ultralytics_bytetrack import (
    UltralyticsVehicleTracker,
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

    if not settings.vehicle_model_path.is_file():
        raise ValueError(
            "vehicle_model_path가 실제 vehicle model 파일이 아닙니다: "
            f"{settings.vehicle_model_path}"
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
    )
    frame_source = RemapFrameSource(
        inner=webcam,
        calibration_path=str(settings.calibration_path),
        balance=settings.remap_balance,
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
) -> FastAPI:
    """FastAPI app을 만들고 process-local 자원 생명주기를 소유한다.

    module-level app은 운영 concrete factory를 전달해 camera·tracking
    monitoring을 함께 기동한다. 직접 호출하는 API-only 테스트는 factory를
    생략하거나 별도 test double을 주입할 수 있다.
    """

    resolved_settings = settings or get_settings()

    def connection_factory() -> sqlite3.Connection:
        # FastAPI sync handler와 monitoring thread가 SQLite connection을
        # 공유하지 않도록 호출마다 새로 연다.
        return connect_database(resolved_settings.database_path)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
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
        application.state.entry_event_intake = EntryEventIntake(
            entry_match_coordinator,
            match_window_seconds=(
                resolved_settings.entry_match_window_seconds
            ),
        )
        application.state.entry_review_resolution_intake = (
            EntryReviewResolutionIntake(entry_match_coordinator)
        )
        application.state.session_context_update_intake = (
            SessionContextUpdateIntake(ContextBindingCoordinator())
        )
        application.state.move_verification_intake = MoveVerificationIntake()
        application.state.database_connection_factory = connection_factory
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

        monitoring_worker: MonitoringWorker | None = None
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
            monitoring_worker = MonitoringWorker(
                pipeline, frame_observer=overlay_publisher
            )
        application.state.monitoring_worker = monitoring_worker

        move_verification_worker = MoveVerificationExecutorWorker(
            MoveVerificationExecutor(
                connection_factory=connection_factory,
                publication_preparer=publication_preparer,
            )
        )
        application.state.move_verification_worker = move_verification_worker

        evidence_publication_worker: EvidencePublicationWorker | None = None
        outbox_publisher_worker: OutboxPublisherWorker | None = None
        if resolved_settings.backend_hw_api_key.strip():
            evidence_publication_worker = EvidencePublicationWorker(
                EvidencePublicationPublisher(
                    connection_factory=connection_factory,
                    client=BackendClient(
                        base_url=resolved_settings.backend_base_url,
                        hw_api_key=resolved_settings.backend_hw_api_key,
                    ),
                    spool_path=resolved_settings.evidence_spool_path,
                    spool_cap_bytes=(
                        resolved_settings.evidence_spool_cap_bytes
                    ),
                    filesystem_floor_ratio=(
                        resolved_settings.evidence_filesystem_floor_ratio
                    ),
                    capture_stop_free_ratio=(
                        resolved_settings.evidence_capture_stop_free_ratio
                    ),
                    diagnostics_sink=diagnostics_sink,
                )
            )
            outbox_publisher_worker = OutboxPublisherWorker(
                OutboxPublisher(
                    connection_factory=connection_factory,
                    client=BackendClient(
                        base_url=resolved_settings.backend_base_url,
                        hw_api_key=resolved_settings.backend_hw_api_key,
                    ),
                )
            )
        else:
            logger.warning(
                "BACKEND_HW_API_KEY가 비어 Backend publication worker를 "
                "비활성화합니다."
            )
        application.state.evidence_publication_worker = (
            evidence_publication_worker
        )
        application.state.outbox_publisher_worker = outbox_publisher_worker
        try:
            # MonitoringPipeline.open()이 durable recovery를 끝낸 뒤 기존·신규
            # publication을 보내기 시작한다.
            if evidence_publication_worker is not None:
                evidence_publication_worker.start()
            else:
                # Backend key가 없어 publisher를 끈 현장도 interrupted local
                # JPEG를 다음 capture 전 일관된 FAILED/READY 상태로 만든다.
                evidence_capture_coordinator.recover()
            if monitoring_worker is not None:
                monitoring_worker.start()
            move_verification_worker.start()
            if outbox_publisher_worker is not None:
                outbox_publisher_worker.start()
                logger.info("Backend publication workers가 시작됐습니다.")
            yield
        finally:
            _stop_workers_best_effort(
                (
                    ("monitoring", monitoring_worker),
                    ("move verification", move_verification_worker),
                    ("outbox publication", outbox_publisher_worker),
                    ("evidence publication", evidence_publication_worker),
                ),
                # worker start 또는 lifespan 본문 예외를 shutdown 오류로
                # 덮어쓰지 않는다.
                suppress_errors=sys.exc_info()[1] is not None,
            )

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
    """운영 camera·tracking factory가 결속된 ASGI app을 생성한다."""

    return create_app(
        monitoring_pipeline_factory=build_runtime_monitoring_pipeline,
    )


def _prepare_database_path(database_path: Path) -> None:
    """File DB의 부모 디렉터리만 기동 시 준비한다."""

    if str(database_path) != ":memory:":
        database_path.parent.mkdir(parents=True, exist_ok=True)


configure_logging()
app = _create_runtime_app()
