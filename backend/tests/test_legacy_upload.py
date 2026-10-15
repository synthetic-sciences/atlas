import json
import time
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import httpx
import pytest

from atlas_graph.db.connection import get_db
from atlas_graph.integrations.dashboard import Dashboard
from atlas_graph.runtime import Host, configure
from atlas_graph.services import artifact_service


async def prepare(client):
    project = (
        await client.post("/api/v1/projects", json={"title": "Pending upload"})
    ).json()["project_id"]
    response = await client.post(
        f"/api/v1/nodes/{project}/artifacts/uploads/prepare",
        json={
            "expected_revision": 0,
            "items": [
                {
                    "filename": "evidence.bin",
                    "artifact_type": "binary",
                    "media_type": "application/octet-stream",
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    return project, response.json()


async def test_legacy_ticket_uses_scoped_account_verification_and_preserves_large_uploads(
    client, monkeypatch
):
    graph_secret = uuid4().hex
    monkeypatch.setenv("ATLAS_SIGNING_SECRET", graph_secret)
    project, batch = await prepare(client)
    item = batch["items"][0]
    claims = {
        "upload_id": item["upload_id"],
        "node_id": project,
        "batch_token": batch["batch_token"],
        "content_type": "application/octet-stream",
        "iat": int(time.time()),
        "exp": int(time.time()) + 900,
    }
    with monkeypatch.context() as context:
        context.setenv("ATLAS_SIGNING_SECRET", uuid4().hex)
        ticket = artifact_service._sign_upload_ticket(
            item["upload_id"],
            project,
            batch["batch_token"],
            "application/octet-stream",
            900,
        )
    calls = []
    token = uuid4().hex

    def verify(request):
        assert (
            str(request.url)
            == "https://dashboard.example/api/internal/atlas/upload-ticket"
        )
        assert request.headers["x-atlas-service-token"] == token
        assert (
            "authorization" not in request.headers
            and "x-atlas-index-token" not in request.headers
        )
        assert json.loads(request.content) == {"ticket": ticket}
        calls.append(request)
        return httpx.Response(200, json=claims)

    remote = Dashboard(
        "https://dashboard.example",
        token,
        client=httpx.AsyncClient(transport=httpx.MockTransport(verify)),
    )
    configure(Host(upload_ticket=remote.upload_ticket))
    url = urlsplit(item["upload_url"])
    url = urlunsplit(url._replace(query=urlencode({"ticket": f"v1:{ticket}"})))
    data = b"evidence" * (256 * 1024)
    try:
        uploaded = await client.put(
            url,
            content=data,
            headers={
                "Content-Type": "application/octet-stream",
                "Idempotency-Key": "large-slot",
            },
        )
        assert uploaded.status_code == 200, uploaded.text
        assert len(calls) == 1
        finalized = await client.post(
            f"/api/v1/nodes/{project}/artifacts/uploads/finalize",
            json={"batch_token": batch["batch_token"]},
        )
        assert finalized.status_code == 200, finalized.text
        artifact = (await client.get(f"/api/v1/nodes/{project}/artifacts")).json()[0]
        downloaded = await client.get(
            artifact["storage_url"], headers={"Authorization": ""}
        )
        assert downloaded.status_code == 200 and downloaded.content == data
        assert len(calls) == 1
    finally:
        configure(Host())
        await remote.close()


async def test_upload_claims_must_match_actual_batch_and_expired_batches_refuse_bytes(
    client,
):
    project, batch = await prepare(client)
    item = batch["items"][0]
    wrong = artifact_service._sign_upload_ticket(
        item["upload_id"],
        str(uuid4()),
        batch["batch_token"],
        "application/octet-stream",
        900,
    )
    url = urlsplit(item["upload_url"])
    wrong_url = urlunsplit(url._replace(query=urlencode({"ticket": f"v1:{wrong}"})))
    response = await client.put(wrong_url, content=b"wrong project")
    assert response.status_code == 403, response.text
    async with get_db() as db:
        await db.execute(
            "UPDATE artifact_upload_batches SET expires_at='2000-01-01T00:00:00Z' WHERE batch_token=?",
            (batch["batch_token"],),
        )
        await db.commit()
    expired = await client.put(item["upload_url"], content=b"expired batch")
    assert expired.status_code == 403, expired.text


async def test_legacy_authenticated_upload_checks_node_write_access(client):
    _, batch = await prepare(client)
    upload = batch["items"][0]["upload_id"]

    async def other(request):
        return {"user_id": str(uuid4())}

    configure(Host(authenticate=other))
    try:
        refused = await client.put(
            f"/api/artifacts/upload/{upload}", content=b"another user's bytes"
        )
        assert refused.status_code == 403, refused.text
    finally:
        configure(Host())


def test_exported_route_catalog_covers_graph_paths_and_excludes_control_routes():
    from atlas_graph.contract import routes

    catalog = routes()
    projects = next(route for route in catalog if route["path"] == "/api/v1/projects")
    assert set(projects["methods"]) == {"GET", "POST"}
    assert {"path": "/api/artifacts/download/{path:path}", "methods": ["GET"]} in catalog
    assert {"path": "/api/knowledge/search", "methods": ["POST"]} in catalog
    assert not any(route["path"].startswith("/api/internal/") for route in catalog)
    assert not any(
        route["path"] in {"/api/v1/auth/status", "/api/health", "/api/v1/auth/api-keys"}
        for route in catalog
    )
    assert all(route["path"].startswith("/api/") for route in catalog)
