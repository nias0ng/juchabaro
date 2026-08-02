"""Jetson API와 단일 monitoring owner의 process 생명주기를 조립한다.

DB migration·ZoneDefinition 검증·inbound application 조립은 항상 수행한다.
Camera·model pipeline은 exact Backend publication wire와 장치 adapter를 소유한
배포 계층이 ``MonitoringPipelineFactory``를 제공했을 때만 기동한다.
이 경계 덕분에 API 계약 확정 전에 임시 serializer나 no-op publisher를
실행 경로에 넣지 않는다.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI

from src.api.entry_events_router import router as entry_events_router
from src.api.health_router import router as health_router
from src.application.entry_event_intake import EntryEventIntake
from src.application.monitoring_pipeline import MonitoringPipeline
from src.application.monitoring_worker import MonitoringWorker
from src.config.settings import Settings, get_settings
from src.parking.zone_registry import ZoneRegistry
from src.session.entry_match_coordinator import EntryMatchCoordinator
from src.storage.database import connect_database, open_database


DatabaseConnectionFactory = Callable[[], sqlite3.Connection]


@dataclass(frozen=True)
class RuntimeContext:
    """확정된 기동 설정·구역·DB connection 경계."""

    settings: Settings
    zones: ZoneRegistry
    connection_factory: DatabaseConnectionFactory


MonitoringPipelineFactory = Callable[[RuntimeContext], MonitoringPipeline]


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

    module-level app은 inbound API만 조립한다. 후속 Backend·hardware
    계약을 구현한 배포 entrypoint는 factory를 주입해 같은 process에서
    monitoring을 단 하나만 실행한다.
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
        entry_match_coordinator = EntryMatchCoordinator(zones=zones)
        application.state.zone_registry = zones
        application.state.entry_match_coordinator = entry_match_coordinator
        application.state.entry_event_intake = EntryEventIntake(
            entry_match_coordinator,
            match_window_seconds=(
                resolved_settings.entry_match_window_seconds
            ),
        )
        application.state.database_connection_factory = connection_factory

        monitoring_worker: MonitoringWorker | None = None
        if monitoring_pipeline_factory is not None:
            pipeline = monitoring_pipeline_factory(
                RuntimeContext(
                    settings=resolved_settings,
                    zones=zones,
                    connection_factory=connection_factory,
                )
            )
            monitoring_worker = MonitoringWorker(pipeline)
            monitoring_worker.start()
        application.state.monitoring_worker = monitoring_worker
        try:
            yield
        finally:
            if monitoring_worker is not None:
                monitoring_worker.stop()

    application = FastAPI(
        title=resolved_settings.app_name,
        version="0.1.0",
        description="Smart Parking Jetson hardware interface",
        lifespan=lifespan,
    )

    application.include_router(health_router)
    application.include_router(entry_events_router)

    return application


def _prepare_database_path(database_path: Path) -> None:
    """File DB의 부모 디렉터리만 기동 시 준비한다."""

    if str(database_path) != ":memory:":
        database_path.parent.mkdir(parents=True, exist_ok=True)


configure_logging()
app = create_app()
