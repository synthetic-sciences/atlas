"""A graph login cannot read private Dashboard tables on the same PG server."""

import os
from urllib.parse import quote, urlsplit, urlunsplit
from uuid import uuid4

import httpx
import pytest

asyncpg = pytest.importorskip("asyncpg")

pytestmark = pytest.mark.skipif(
    not os.environ.get("ATLAS_TEST_PG_DSN"),
    reason="An isolated graph PostgreSQL database is required",
)


async def test_graph_role_owns_its_schema_and_cannot_read_platform_tables(
    tmp_path, monkeypatch
):
    parsed = urlsplit(os.environ["ATLAS_TEST_PG_DSN"])
    assert parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    assert parsed.path.startswith("/atlas_graph_")
    name = f"atlas_graph_isolation_{uuid4().hex}"
    role = f"atlas_role_{uuid4().hex}"
    password = uuid4().hex
    admin = await asyncpg.connect(urlunsplit(parsed))
    owner = None
    from atlas_graph.db.connection import close_db, get_db, init_db

    try:
        await admin.execute(f'CREATE DATABASE "{name}"')
        owner = await asyncpg.connect(urlunsplit(parsed._replace(path=f"/{name}")))
        await owner.execute(
            "CREATE EXTENSION vector; CREATE TABLE public.users (user_id uuid PRIMARY KEY, password_hash text NOT NULL); CREATE TABLE public.nodes (private_title text NOT NULL); INSERT INTO public.nodes VALUES ('Private platform fixture')"
        )
        await owner.execute(
            f"CREATE ROLE \"{role}\" LOGIN PASSWORD '{password}' NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS"
        )
        await owner.execute(f'CREATE SCHEMA graph AUTHORIZATION "{role}"')
        address = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
        netloc = f"{quote(role)}:{quote(password)}@{address}:{parsed.port or 5432}"
        monkeypatch.setenv(
            "ATLAS_DATABASE_URL",
            urlunsplit(parsed._replace(netloc=netloc, path=f"/{name}")),
        )
        monkeypatch.setenv("ATLAS_DATABASE_SCHEMA", "graph")
        monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("ATLAS_MODE", "local")
        await init_db()
        await init_db()
        from atlas_graph.main import app

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://127.0.0.1",
            headers={"Authorization": "Bearer local"},
        ) as client:
            created = await client.post(
                "/api/v1/projects", json={"title": "Isolated graph", "dedupe_key": name}
            )
            assert created.status_code == 201, created.text
            project = created.json()["project_id"]
            repeated = await client.post(
                "/api/v1/projects", json={"title": "Isolated graph", "dedupe_key": name}
            )
            assert repeated.json()["project_id"] == project
            assert repeated.json()["deduped"] is True
            assert (
                await client.get(f"/api/nodes/{project}/tree?projection=full")
            ).status_code == 200
        async with get_db() as db:
            cursor = await db.execute("SELECT current_schema() AS namespace")
            assert (await cursor.fetchone())["namespace"] == "graph"
            for table in ("users", "nodes"):
                with pytest.raises(asyncpg.InsufficientPrivilegeError):
                    await db.execute(f"SELECT * FROM public.{table}")
        assert await owner.fetchval("SELECT COUNT(*) FROM graph.nodes") == 1
        assert await owner.fetchval("SELECT COUNT(*) FROM public.nodes") == 1
        assert await owner.fetchval("SELECT COUNT(*) FROM public.users") == 0
    finally:
        await close_db()
        if owner is not None:
            await owner.close()
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}"')
        await admin.execute(f'DROP ROLE IF EXISTS "{role}"')
        await admin.close()


@pytest.mark.parametrize(
    "namespace", ["missing_graph_namespace", "public; DROP SCHEMA public CASCADE"]
)
async def test_invalid_or_missing_graph_namespace_fails_without_fallback(
    tmp_path, monkeypatch, namespace
):
    parsed = urlsplit(os.environ["ATLAS_TEST_PG_DSN"])
    assert parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    assert parsed.path.startswith("/atlas_graph_")
    monkeypatch.setenv("ATLAS_DATABASE_URL", urlunsplit(parsed))
    monkeypatch.setenv("ATLAS_DATABASE_SCHEMA", namespace)
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path))
    from atlas_graph.db.connection import close_db, init_db

    try:
        with pytest.raises(RuntimeError, match="schema|identifier"):
            await init_db()
    finally:
        await close_db()
