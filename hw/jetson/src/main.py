import logging

from fastapi import FastAPI

from src.api.health_router import router as health_router
from src.config.settings import get_settings


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

    return application


configure_logging()
app = create_app()