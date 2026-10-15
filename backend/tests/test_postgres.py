import os
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import pytest


@pytest.mark.skipif(not os.environ.get("ATLAS_TEST_PG_DSN"), reason="An isolated graph PostgreSQL database is required")
async def test_graph_postgres_initialization_and_project_contract(tmp_path, monkeypatch):
    dsn = os.environ["ATLAS_TEST_PG_DSN"]
    parsed = urlsplit(dsn)
    assert parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    assert parsed.path.startswith("/atlas_graph_")
    monkeypatch.setenv("ATLAS_DATABASE_URL", dsn)
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ATLAS_MODE", "local")
    from atlas_graph.db.connection import close_db, get_db, init_db
    from atlas_graph.main import app

    await init_db()
    await init_db()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1", headers={"Authorization": "Bearer local"}) as client:
            marker = f"pg:{uuid4()}"
            first = await client.post("/api/v1/projects", json={"title": "Independent PostgreSQL graph", "dedupe_key": marker})
            assert first.status_code == 201, first.text
            second = await client.post("/api/v1/projects", json={"title": "Independent PostgreSQL graph", "dedupe_key": marker})
            assert second.json()["project_id"] == first.json()["project_id"]
            assert second.json()["deduped"] is True
            assert (await client.get(f"/api/nodes/{first.json()['project_id']}/tree?projection=full")).status_code == 200
        async with get_db() as db:
            cursor = await db.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
            names = {row[0] for row in await cursor.fetchall()}
        assert {"nodes", "node_edges", "artifacts", "research_log"} <= names
        assert not names.intersection({"credit_transactions", "api_keys", "organizations", "telemetry_events"})
    finally:
        await close_db()

