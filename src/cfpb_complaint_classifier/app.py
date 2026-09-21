from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from cfpb_complaint_classifier.api import health, version
from cfpb_complaint_classifier.core.config import get_settings
from cfpb_complaint_classifier.core.version import get_application_version
from cfpb_complaint_classifier.db.engine import create_engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.db_engine = create_engine(get_settings())
    try:
        yield
    finally:
        await app.state.db_engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="CFPB Complaint Classifier",
        version=get_application_version(),
        lifespan=lifespan,
    )
    app.include_router(health.router)
    app.include_router(version.router)
    return app


app = create_app()
