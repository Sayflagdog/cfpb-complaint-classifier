from importlib.metadata import version


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
