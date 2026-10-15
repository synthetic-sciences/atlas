import os

import httpx
import pytest_asyncio


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ATLAS_MODE", "local")
    monkeypatch.delenv("ATLAS_DATABASE_URL", raising=False)
    monkeypatch.delenv("ATLAS_LOCAL_TOKEN", raising=False)
    from atlas_graph.db.connection import close_db, init_db
    from atlas_graph.main import app

    await init_db()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1", headers={"Authorization": "Bearer local"}) as instance:
        yield instance
    await close_db()

