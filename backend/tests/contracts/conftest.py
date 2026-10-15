import httpx
import pytest
import pytest_asyncio

from atlas_graph.dependencies import LOCAL_USER_ID


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ATLAS_MODE", "local")
    monkeypatch.delenv("ATLAS_DATABASE_URL", raising=False)
    monkeypatch.delenv("ATLAS_LOCAL_TOKEN", raising=False)
    from atlas_graph.db.connection import close_db, init_db
    from atlas_graph.main import app

    await init_db()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as instance:
        assert (await instance.get("/api/v1/auth/status", headers={"Authorization": "Bearer local"})).status_code == 200
        yield instance
    await close_db()


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer local", "X-Test-User-Id": LOCAL_USER_ID}


@pytest_asyncio.fixture
async def db_with_user(client):
    from atlas_graph.db.connection import get_db

    async with get_db() as db:
        yield db, LOCAL_USER_ID
