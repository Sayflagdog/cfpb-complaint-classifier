import asyncio
import os
import time
from unittest.mock import Mock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from testcontainers.community.postgres import PostgresContainer
from testcontainers.community.rabbitmq import RabbitMqContainer

from cfpb_complaint_classifier import app as app_module
from cfpb_complaint_classifier import worker as worker_module
from cfpb_complaint_classifier.core.config import Settings
from cfpb_complaint_classifier.db.engine import create_engine
from cfpb_complaint_classifier.db.tasks import (
    create_schema,
    get_result,
    save_result,
    task_results,
)
from cfpb_complaint_classifier.messaging import (
    QueueOverloadedError,
    create_broker,
    declare_topology,
    publish_task,
    task_queue,
)
from cfpb_complaint_classifier.schemas import TaskMessage
from cfpb_complaint_classifier.services.inference import LoadedModel
from cfpb_complaint_classifier.source import publish_file, read_tasks

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_INTEGRATION_TESTS") != "1",
        reason="Set RUN_INTEGRATION_TESTS=1 and start Docker",
    ),
]


@pytest.fixture(scope="module")
def services():
    with (
        RabbitMqContainer("rabbitmq:4.1.8-management-alpine") as rabbit,
        PostgresContainer("postgres:16-alpine", driver="asyncpg") as postgres,
    ):
        yield Settings(
            _env_file=None,
            rabbitmq_url=(
                f"amqp://guest:guest@{rabbit.get_container_host_ip()}:"
                f"{rabbit.get_exposed_port(5672)}/"
            ),
            database_url=postgres.get_connection_url(),
            task_queue_name=f"test.{uuid4().hex}",
            queue_max_length=2,
            worker_concurrency=1,
            inference_delay_seconds=0.1,
        )


async def test_overflow_source_resume_api_rejection_and_unique_results(
    services, tmp_path, monkeypatch
):
    settings = services
    monkeypatch.setattr(app_module, "get_settings", lambda: settings)
    monkeypatch.setattr(app_module, "create_broker", create_broker)
    monkeypatch.setattr(app_module, "declare_topology", declare_topology)
    model = LoadedModel(
        Mock(predict=Mock(return_value=["Debt collection"])), "test", "7"
    )
    monkeypatch.setattr(worker_module, "load_registered_model", lambda settings: model)
    engine = create_engine(settings)
    await create_schema(engine)
    app = app_module.create_app()
    first = TaskMessage(task_id=uuid4(), text="first debt complaint")
    second = TaskMessage(task_id=uuid4(), text="second debt complaint")
    path = tmp_path / "batch.csv"
    path.write_text("text\nthird debt complaint\nfourth debt complaint\n")
    source_job = None
    try:
        async with (
            create_broker(settings) as broker,
            app.router.lifespan_context(app),
            AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client,
        ):
            await declare_topology(broker, settings)
            await publish_task(broker, settings, first)
            await publish_task(broker, settings, second)
            with pytest.raises(QueueOverloadedError):
                await publish_task(
                    broker, settings, TaskMessage(task_id=uuid4(), text="overflow")
                )
            queue = await broker.declare_queue(task_queue(settings))
            await queue.declare()
            assert queue.declaration_result.message_count == settings.queue_max_length
            started = time.monotonic()
            rejected_id = uuid4()
            response = await asyncio.wait_for(
                client.post(
                    "/api/v1/tasks", json={"text": "debt", "task_id": str(rejected_id)}
                ),
                timeout=2,
            )
            assert response.status_code == 503
            assert response.headers["Retry-After"] == "1"
            assert time.monotonic() - started < 2
            assert await get_result(engine, rejected_id) is None
            source_job = asyncio.create_task(
                publish_file(path, "integration", settings)
            )
            await asyncio.sleep(0.15)
            assert not source_job.done()

            worker = worker_module.create_worker_app(settings)
            async with worker.router.lifespan_context(worker):
                assert await asyncio.wait_for(source_job, timeout=10) == 2
                task_ids = [first.task_id, second.task_id] + [
                    task.task_id for task in read_tasks(path, "integration")
                ]
                for _ in range(200):
                    if all([await get_result(engine, task_id) for task_id in task_ids]):
                        break
                    await asyncio.sleep(0.05)
                else:
                    pytest.fail("Accepted tasks did not reach PostgreSQL")
                response = await client.get(f"/api/v1/tasks/{first.task_id}")
                assert response.status_code == 200
                assert response.json()["model_version"] == "7"
                result = await get_result(engine, first.task_id)
                await asyncio.gather(
                    save_result(engine, result), save_result(engine, result)
                )
                async with engine.connect() as connection:
                    assert await connection.scalar(
                        select(func.count()).select_from(task_results)
                    ) == len(task_ids)
    finally:
        if source_job is not None and not source_job.done():
            source_job.cancel()
            await asyncio.gather(source_job, return_exceptions=True)
        await engine.dispose()
