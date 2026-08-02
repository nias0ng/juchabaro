"""Jetson inbound API process를 조립한다.

이 process는 durable 입차 접수와 health를 소유한다. Camera·model owner는
Backend publication wire와 배포 설정이 확정된 뒤
``application.monitoring_factory``를 사용하는 단일 worker로 기동한다.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from src.api.entry_events_router import router as entry_events_router
from src.api.health_router import router as health_router
from src.application.entry_event_intake import EntryEventIntake
from src.config.settings import get_settings
from src.parking.zone_registry import ZoneRegistry
from src.session.entry_match_coordinator import EntryMatchCoordinator
from src.storage.database import connect_database, open_database


def configure_logging() -> None:
    settings = get_settings()

    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(_application: FastAPI):
        """DB migration·integrity check를 기동 시 한 번만 수행한다."""

        _prepare_database_path(settings.database_path)
        connection = open_database(settings.database_path)
        connection.close()
        yield

    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Smart Parking Jetson hardware interface",
        lifespan=lifespan,
    )

    application.include_router(health_router)
    application.include_router(entry_events_router)
    zone_registry = ZoneRegistry.from_file(settings.zone_definition_path)
    entry_match_coordinator = EntryMatchCoordinator(
        zones=zone_registry,
    )
    application.state.zone_registry = zone_registry
    application.state.entry_match_coordinator = entry_match_coordinator
    application.state.entry_event_intake = EntryEventIntake(
        entry_match_coordinator,
        match_window_seconds=settings.entry_match_window_seconds,
    )
    # FastAPI sync handler마다 새 connection을 열어 SQLite의
    # check_same_thread 계약을 지킨다. Tracking worker도 별도 connection을 사용한다.
    application.state.database_connection_factory = lambda: connect_database(
        settings.database_path
    )

    return application


def _prepare_database_path(database_path: Path) -> None:
    """File DB의 부모 디렉터리만 기동 시 준비한다."""

    if str(database_path) != ":memory:":
        database_path.parent.mkdir(parents=True, exist_ok=True)


configure_logging()
app = create_app()
