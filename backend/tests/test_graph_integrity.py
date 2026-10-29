import asyncio
import base64
import copy
import hashlib
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response

from atlas_graph.db.connection import close_db, get_db, init_db
from atlas_graph.dependencies import LOCAL_USER_ID
from atlas_graph.middleware.idempotency import IdempotencyMiddleware, _storage_key


@pytest_asyncio.fixture(params=["sqlite", "postgres"])
async def integrity_client(request, tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ATLAS_MODE", "local")
    monkeypatch.delenv("ATLAS_LOCAL_TOKEN", raising=False)
    monkeypatch.delenv("ATLAS_DATABASE_URL", raising=False)
    admin = None
    schema = "audit_" + uuid4().hex
    if request.param == "postgres":
        dsn = os.environ.get("ATLAS_TEST_PG_DSN")
        if not dsn:
            pytest.skip("An isolated graph PostgreSQL database is required")
        parsed = urlsplit(dsn)
        assert parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        assert parsed.path.startswith("/atlas_graph_")
        import asyncpg

        admin = await asyncpg.connect(dsn)
        await admin.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
        await admin.execute(f'CREATE SCHEMA "{schema}"')
        monkeypatch.setenv("ATLAS_DATABASE_URL", dsn)
        monkeypatch.setenv("ATLAS_DATABASE_SCHEMA", schema)
    from atlas_graph.main import app

    try:
        await init_db()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1",
            headers={"Authorization": "Bearer local"},
        ) as client:
            assert (await client.get("/api/v1/auth/status")).status_code == 200
            yield client
    finally:
        await close_db()
        if admin:
            await admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
            await admin.close()


async def create(client, title="Graph", **fields):
    response = await client.post("/api/nodes/stage-create", json={"title": title, **fields})
    assert response.status_code == 201, response.text
    return response.json()


async def test_child_creation_checks_every_parent_before_writing(integrity_client):
    client = integrity_client
    private = await create(client, "Private graph")
    owned = await create(client, "Own graph")
    response = await client.post("/api/tags", json={
        "root_node_id": private["node_id"], "expected_revision": 0, "name": "Private evidence label",
    })
    assert response.status_code == 201, response.text
    victim = str(uuid4())
    now = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        await db.execute("INSERT INTO users (user_id,email,created_at,updated_at) VALUES (?,?,?,?)", (victim, f"{victim}@atlas.invalid", now, now))
        await db.execute("UPDATE nodes SET owner_user_id=? WHERE node_id=?", (victim, private["node_id"]))
        await db.commit()
    assert (await client.get(f"/api/nodes/{private['node_id']}")).status_code == 403
    for endpoint in ("/api/nodes/stage-create", "/api/v1/nodes/commit-new"):
        denied = await client.post(endpoint, json={"title": "Unauthorized", "parent_ids": [owned["node_id"], private["node_id"]]})
        assert denied.status_code == 403, denied.text
        assert "Private evidence label" not in denied.text
    async with get_db() as db:
        assert (await db.execute_fetchall("SELECT COUNT(*) AS count FROM nodes"))[0]["count"] == 2
        assert (await db.execute_fetchall("SELECT COUNT(*) AS count FROM node_edges"))[0]["count"] == 0
    child = await create(client, parent_ids=[owned["node_id"]])
    assert child["parent_ids"] == [owned["node_id"]]


async def test_branching_claims_the_parent_revision_once(integrity_client):
    client = integrity_client
    parent = await create(client)
    results = await asyncio.gather(*[
        client.post("/api/nodes/branch", json={"node_id": parent["node_id"], "expected_revision": 0, "title": f"Branch {index}"})
        for index in range(10)
    ])
    assert [response.status_code for response in results].count(201) == 1
    assert [response.status_code for response in results].count(409) == 9
    node = (await client.get(f"/api/nodes/{parent['node_id']}")).json()
    assert node["revision"] == 1
    assert len(node["child_ids"]) == 1


async def test_idempotency_claims_before_concurrent_dispatch(integrity_client):
    client = integrity_client
    body = {"title": "Exactly one node"}
    headers = {"Idempotency-Key": "concurrent-create"}
    responses = await asyncio.gather(*[
        client.post("/api/nodes/stage-create", json=body, headers=headers) for _ in range(10)
    ])
    assert all(response.status_code in {201, 409} for response in responses)
    successful = [response.json()["node_id"] for response in responses if response.status_code == 201]
    assert len(set(successful)) == 1
    replay = await client.post("/api/nodes/stage-create", json=body, headers=headers)
    assert replay.status_code == 201
    assert replay.json()["node_id"] == successful[0]
    different = await client.post("/api/nodes/stage-create", json={"title": "Different"}, headers=headers)
    assert different.status_code == 409
    async with get_db() as db:
        assert (await db.execute_fetchall("SELECT COUNT(*) AS count FROM nodes"))[0]["count"] == 1


async def test_ambiguous_mutation_is_not_dispatched_again_after_expiry(integrity_client):
    app = FastAPI()
    app.add_middleware(IdempotencyMiddleware)
    attempts = []

    @app.post("/ambiguous")
    async def ambiguous():
        attempts.append(True)
        return JSONResponse(status_code=500, content={"detail": "Response failed after a possible commit"})

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1", headers={"Authorization": "Bearer local", "Idempotency-Key": "ambiguous"}) as client:
        assert (await client.post("/ambiguous", json={})).status_code == 500
        async with get_db() as db:
            await db.execute("UPDATE idempotency_keys SET expires_at=? WHERE idempotency_key=?", (
                (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
                _storage_key(LOCAL_USER_ID, "POST", "/ambiguous", "ambiguous"),
            ))
            await db.commit()
        response = await client.post("/ambiguous", json={})
        assert response.status_code == 409
        assert "unknown" in response.text
        assert len(attempts) == 1


async def test_replay_bounds_the_measured_response_size(integrity_client):
    app = FastAPI()
    app.add_middleware(IdempotencyMiddleware)
    attempts = []

    @app.post("/large")
    async def large():
        attempts.append(True)
        return Response(content=b'"' + b"x" * 1_048_576 + b'"', media_type="application/json", headers={"Content-Length": "1"})

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1", headers={"Authorization": "Bearer local", "Idempotency-Key": "large"}) as client:
        first = await client.post("/large", json={})
        assert first.status_code == 200
        assert len(first.content) > 1_048_576
        second = await client.post("/large", json={})
        assert second.status_code == 409
        assert "cannot be replayed" in second.text
        assert len(attempts) == 1
        async with get_db() as db:
            rows = await db.execute_fetchall("SELECT response_body FROM idempotency_keys WHERE idempotency_key=?", (_storage_key(LOCAL_USER_ID, "POST", "/large", "large"),))
            assert len(rows[0]["response_body"]) < 1_048_576


async def upload(client, node, content):
    prepared = await client.post(f"/api/v1/nodes/{node['node_id']}/artifacts/uploads/prepare", json={
        "expected_revision": node["revision"],
        "items": [{"filename": "evidence.bin", "artifact_type": "binary", "media_type": "application/octet-stream", "title": "Measured evidence", "note": "Reproduce this", "metadata": {"experiment": 42}}],
    })
    assert prepared.status_code == 201, prepared.text
    batch = prepared.json()
    response = await client.put(batch["items"][0]["upload_url"], content=content, headers={"Content-Type": "application/octet-stream"})
    assert response.status_code in {200, 201, 204}, response.text
    response = await client.post(f"/api/v1/nodes/{node['node_id']}/artifacts/uploads/finalize", json={"batch_token": batch["batch_token"]})
    assert response.status_code == 200, response.text
    return (await client.get(f"/api/v1/nodes/{node['node_id']}/artifacts")).json()[0]


async def test_archive_restores_evidence_bytes_metadata_and_fresh_ids(integrity_client):
    client = integrity_client
    node = await create(client)
    content = bytes(range(256)) * 4096  # Exceeds generic middleware's JSON-body limit when encoded.
    original = await upload(client, node, content)
    async with get_db() as db:
        import json

        await db.execute("UPDATE nodes SET semantic_data=? WHERE node_id=?", (json.dumps({"evidence": {"node_id": node["node_id"], "artifact_id": original["artifact_id"]}}), node["node_id"]))
        await db.commit()
    exported = await client.post("/api/export/subgraph", json={"node_ids": [node["node_id"]]}, headers={"Idempotency-Key": "export"})
    assert exported.status_code == 200, exported.text
    archive = exported.json()
    assert archive["version"] == 2
    blob = archive["nodes"][0]["artifacts"][0]["blob"]
    assert base64.b64decode(blob["data"]) == content
    assert blob["sha256"] == hashlib.sha256(content).hexdigest()
    imported = await client.post("/api/import/subgraph", json=archive, headers={"Idempotency-Key": "import"})
    assert imported.status_code == 201, imported.text
    restored = imported.json()["id_mapping"][node["node_id"]]
    artifacts = (await client.get(f"/api/v1/nodes/{restored}/artifacts")).json()
    assert len(artifacts) == 1
    item = artifacts[0]
    assert item["artifact_id"] != original["artifact_id"]
    assert item["storage_path"] != original["storage_path"]
    assert item["title"] == original["title"]
    assert item["note"] == original["note"]
    assert item["metadata"] == original["metadata"]
    assert (await client.get(item["storage_url"])).content == content
    async with get_db() as db:
        rows = await db.execute_fetchall("SELECT semantic_data FROM nodes WHERE node_id=?", (restored,))
        assert json.loads(rows[0]["semantic_data"])["evidence"] == {"node_id": restored, "artifact_id": item["artifact_id"]}
    replay = await client.post("/api/import/subgraph", json=archive, headers={"Idempotency-Key": "import"})
    assert replay.json() == imported.json()


async def test_archive_rejects_corrupt_or_foreign_storage_without_partial_nodes(integrity_client):
    client = integrity_client
    node = await create(client)
    await upload(client, node, b"private evidence")
    archive = (await client.post("/api/export/subgraph", json={"node_ids": [node["node_id"]]})).json()
    corrupt = copy.deepcopy(archive)
    corrupt["nodes"][0]["artifacts"][0]["blob"]["sha256"] = "0" * 64
    foreign = copy.deepcopy(archive)
    foreign["nodes"][0]["artifacts"][0]["payload"]["storage_path"] = "private/another-user.bin"
    malformed_url = copy.deepcopy(archive)
    malformed_url["nodes"][0]["artifacts"][0]["external_url"] = {"url": "https://example.invalid"}
    malformed_edges = copy.deepcopy(archive)
    malformed_edges["nodes"][0]["incoming_ids"] = [{"node_id": "invalid"}]
    for invalid in (corrupt, foreign, malformed_url, malformed_edges):
        response = await client.post("/api/import/subgraph", json=invalid)
        assert response.status_code == 400, response.text
    async with get_db() as db:
        assert (await db.execute_fetchall("SELECT COUNT(*) AS count FROM nodes"))[0]["count"] == 1
        assert (await db.execute_fetchall("SELECT COUNT(*) AS count FROM artifacts"))[0]["count"] == 1


async def test_legacy_node_only_archives_remain_importable(integrity_client):
    response = await integrity_client.post("/api/import/subgraph", json={
        "version": 1, "nodes": [{"node_id": "legacy-root", "title": "Legacy graph", "node_type": "insight"}],
    })
    assert response.status_code == 201, response.text
    assert response.json()["artifact_count"] == 0
    node = response.json()["id_mapping"]["legacy-root"]
    assert (await integrity_client.get(f"/api/nodes/{node}")).json()["title"] == "Legacy graph"
