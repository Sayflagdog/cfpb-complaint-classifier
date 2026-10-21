import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI
from faststream import AckPolicy

from cfpb_complaint_classifier.api.health import liveness
from cfpb_complaint_classifier.core.config import Settings, get_settings
from cfpb_complaint_classifier.core.logging import setup_logging
from cfpb_complaint_classifier.db.engine import create_engine
from cfpb_complaint_classifier.db.tasks import save_result
from cfpb_complaint_classifier.messaging import (
    create_broker,
    declare_topology,
    task_exchange,
    task_queue,
)
from cfpb_complaint_classifier.schemas import TaskMessage, TaskResult
from cfpb_complaint_classifier.services.inference import load_registered_model

logger = logging.getLogger(__name__)


def create_worker_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    broker = create_broker(settings, consumer=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        setup_logging(settings.log_level)
        engine = create_engine(settings)
        pool = ThreadPoolExecutor(max_workers=settings.worker_concurrency)
        app.state.db_engine = engine
        app.state.pool = pool
        app.state.slots = asyncio.Semaphore(settings.worker_concurrency)
        try:
            app.state.model = await asyncio.get_running_loop().run_in_executor(
                pool, load_registered_model, settings
            )
            async with broker:
                await declare_topology(broker, settings)
                await broker.start()
                logger.info(
                    "Worker ready: concurrency=%d, prefetch=%d, model=%s@%s",
                    settings.worker_concurrency,
                    settings.effective_prefetch_count,
                    app.state.model.name,
                    app.state.model.version,
                )
                yield
        finally:
            await asyncio.to_thread(pool.shutdown, wait=True)
            await engine.dispose()

    app = FastAPI(title="CFPB inference worker", lifespan=lifespan)
    app.state.broker = broker
    app.add_api_route("/healthz", liveness, methods=["GET"])

    @broker.subscriber(
        task_queue(settings),
        task_exchange(settings),
        ack_policy=AckPolicy.REJECT_ON_ERROR,
        no_reply=True,
    )
    async def handle_task(task: TaskMessage) -> None:
        async with app.state.slots:
            started_at = datetime.now(UTC)
            await asyncio.sleep(settings.inference_delay_seconds)
            model = app.state.model
            category = await asyncio.get_running_loop().run_in_executor(
                app.state.pool, model.predict, task.text
            )
            result = TaskResult(
                task_id=task.task_id,
                category=category,
                model_name=model.name,
                model_version=model.version,
                created_at=task.created_at,
                started_at=started_at,
                completed_at=datetime.now(UTC),
            )
            await save_result(app.state.db_engine, result)
            logger.info("Task %s completed", task.task_id)

    return app
