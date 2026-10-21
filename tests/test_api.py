from importlib.metadata import version
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from cfpb_complaint_classifier.api import process
from cfpb_complaint_classifier.messaging import (
    BrokerUnavailableError,
    QueueOverloadedError,
)


async def test_healthz_returns_ok(client):
    response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_version_returns_package_version(client):
    response = await client.get("/api/v1/version")

    assert response.status_code == 200
    assert response.json() == {"version": version("cfpb-complaint-classifier")}


async def test_health_returns_postgres_details(client):
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    assert response.json()["components"]["postgres"]["status"] == "healthy"
    assert response.json()["components"]["postgres"]["version"] == "16.4"
    assert response.json()["components"]["postgres"]["response_time_ms"] >= 0


async def test_health_returns_503_when_postgres_is_unavailable(
    unavailable_client, caplog
):
    response = await unavailable_client.get("/api/v1/health")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["components"]["postgres"]["status"] == "unavailable"
    assert "PostgreSQL health check failed: OSError" in caplog.text
    assert "postgres:postgres" not in caplog.text


async def test_create_task_confirms_publication(client, monkeypatch):
    publish = AsyncMock()
    monkeypatch.setattr(process, "publish_task", publish)
    task_id = str(uuid4())
    response = await client.post(
        "/api/v1/tasks", json={"text": "  debt\n calls  ", "task_id": task_id}
    )
    assert response.status_code == 202
    assert response.json() == {"task_id": task_id}
    task = publish.call_args.args[2]
    assert task.text == "debt calls"
    assert task.task_id == UUID(task_id)
    assert task.created_at.tzinfo is not None


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"text": ""},
        {"text": " \n\t "},
        {"text": None},
        {"text": 42},
        {"text": ["debt"]},
        {"text": "x" * 20001},
        {"text": "debt", "extra": True},
        {"text": "debt", "task_id": "invalid"},
    ],
)
async def test_create_task_validates_input(client, payload):
    assert (await client.post("/api/v1/tasks", json=payload)).status_code == 422


@pytest.mark.parametrize("error", [QueueOverloadedError, BrokerUnavailableError])
async def test_overload_is_not_retried_or_written_to_database(
    client, monkeypatch, error
):
    publish = AsyncMock(side_effect=error)
    save = AsyncMock()
    monkeypatch.setattr(process, "publish_task", publish)
    monkeypatch.setattr("cfpb_complaint_classifier.db.tasks.save_result", save)
    response = await client.post("/api/v1/tasks", json={"text": "debt"})
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "1"
    publish.assert_awaited_once()
    save.assert_not_awaited()


async def test_unknown_result_returns_404(client, monkeypatch):
    monkeypatch.setattr(process, "get_result", AsyncMock(return_value=None))
    assert (await client.get(f"/api/v1/tasks/{uuid4()}")).status_code == 404


async def test_old_process_endpoint_is_removed(client):
    assert (await client.post("/process", json={"text": "debt"})).status_code == 404
