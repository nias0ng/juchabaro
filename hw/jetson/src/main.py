import logging

from fastapi import FastAPI

from src.api.entry_events_router import router as entry_events_router
from src.api.health_router import router as health_router
from src.application.entry_event_intake import EntryEventIntake
from src.config.settings import get_settings
from src.parking.zone_registry import ZoneRegistry
from src.tracking.context_matcher import ContextMatcher


def configure_logging() -> None:
    settings = get_settings()

    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def create_app() -> FastAPI:
    settings = get_settings()

    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Smart Parking Jetson hardware interface",
    )

    application.include_router(health_router)
    application.include_router(entry_events_router)
    zone_registry = ZoneRegistry.from_file(settings.zone_definition_path)
    context_matcher = ContextMatcher(
        zones=zone_registry,
        entry_match_window_seconds=settings.entry_match_window_seconds,
    )
    application.state.zone_registry = zone_registry
    application.state.context_matcher = context_matcher
    application.state.entry_event_intake = EntryEventIntake(context_matcher)

    return application


configure_logging()
app = create_app()
