from contextlib import asynccontextmanager
from types import SimpleNamespace
import asyncio

import pytest


async def test_hosted_maintenance_blocks_api_writes_while_database_health_stays_available(client, monkeypatch):
    monkeypatch.setenv("ATLAS_MODE", "hosted")
    monkeypatch.setenv("ATLAS_SERVING_ENABLED", "false")
    health = await client.get("/api/health/db")
    assert health.status_code == 200
    assert health.json()["serving"] is False
    mutation = await client.post("/api/v1/projects", json={"title": "Must not be created"})
    assert mutation.status_code == 503
    assert mutation.json()["detail"] == "Graph service is in maintenance"
    assert mutation.headers["retry-after"] == "30"
    assert (await client.post("/api/internal/host/graphs", json={})).status_code == 503


async def test_database_readiness_has_a_real_deadline(client, monkeypatch):
    from atlas_graph import main
    async def stalled(*args):
        await asyncio.Event().wait()
    @asynccontextmanager
    async def unavailable():
        yield SimpleNamespace(execute=stalled)
    monkeypatch.setattr(main, "get_db", unavailable)
    response = await asyncio.wait_for(client.get("/api/health/db"), timeout=4)
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "service": "atlas"}


def test_required_hosted_postgres_cannot_silently_use_sqlite(monkeypatch):
    from atlas_graph.hosted import create_app
    monkeypatch.setenv("ATLAS_MODE", "hosted")
    monkeypatch.setenv("ATLAS_REQUIRE_POSTGRES", "true")
    monkeypatch.delenv("ATLAS_DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="requires its graph PostgreSQL database"):
        create_app()


@pytest.mark.parametrize("maximum", ["0", "33", "invalid"])
async def test_graph_pool_rejects_unbounded_capacity(tmp_path, monkeypatch, maximum):
    from atlas_graph.db.connection import init_db
    monkeypatch.setenv("ATLAS_DATABASE_URL", "postgresql://127.0.0.1/atlas_graph_unused")
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ATLAS_PG_POOL_MAX", maximum)
    with pytest.raises(RuntimeError, match="between 1 and 32"):
        await init_db()
