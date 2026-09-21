import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from starlette.responses import Response

from cfpb_complaint_classifier.api import health, version
from cfpb_complaint_classifier.core.config import get_settings
from cfpb_complaint_classifier.core.logging import setup_logging
from cfpb_complaint_classifier.core.version import get_application_version
from cfpb_complaint_classifier.db.engine import create_engine

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    setup_logging(settings.log_level)
    app.state.db_engine = create_engine(settings)
    logger.info("Application started")
    try:
        yield
    finally:
        await app.state.db_engine.dispose()
        logger.info("Application stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="CFPB Complaint Classifier",
        version=get_application_version(),
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def log_requests(request: Request, call_next) -> Response:
        started_at = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
        logger.info(
            "%s %s %s %.2fms",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response

    app.include_router(health.router)
    app.include_router(version.router)
    return app


app = create_app()
