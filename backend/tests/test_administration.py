from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from atlas_graph.contract import routes
from atlas_graph.db.connection import get_db
from atlas_graph.routes.administration import credential


@pytest.mark.parametrize("value", ["", "short", "account" * 8])
def test_administration_requires_a_distinct_service_credential(monkeypatch, value):
    monkeypatch.setenv("ATLAS_ADMIN_SERVICE_TOKEN", value)
    monkeypatch.setenv("ATLAS_ACCOUNT_SERVICE_TOKEN", "account" * 8)
    with pytest.raises(RuntimeError, match="separate service credential"):
        credential()


async def test_host_administration_auth_statistics_exports_and_retention(
    client, monkeypatch
):
    root = (
        await client.post("/api/v1/projects", json={"title": "First graph"})
    ).json()["project_id"]
    second = (
        await client.post("/api/v1/projects", json={"title": "Second graph"})
    ).json()["project_id"]
    async with get_db() as db:
        actor = (
            await (
                await db.execute(
                    "SELECT owner_user_id FROM nodes WHERE node_id=?", (root,)
                )
            ).fetchone()
        )[0]
        old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        await db.execute(
            "INSERT INTO audit_events (event_id,timestamp,operation,node_id) VALUES (?,?,?,?)",
            (str(uuid4()), old, "test", root),
        )
        await db.commit()
    token = uuid4().hex
    headers = {"X-Atlas-Admin-Key": token, "Idempotency-Key": "admin-request"}
    monkeypatch.setenv("ATLAS_ADMIN_SERVICE_TOKEN", token)
    assert (
        await client.post("/api/internal/host/graphs", json={}, headers=headers)
    ).status_code == 404
    monkeypatch.setenv("ATLAS_MODE", "hosted")
    monkeypatch.setenv("ATLAS_SIGNING_SECRET", uuid4().hex)
    assert (await client.post("/api/internal/host/graphs", json={})).status_code == 401
    monkeypatch.delenv("ATLAS_ADMIN_SERVICE_TOKEN")
    assert (await client.post("/api/internal/host/graphs", json={})).status_code == 503
    monkeypatch.setenv("ATLAS_ADMIN_SERVICE_TOKEN", token)
    listing = await client.post(
        "/api/internal/host/graphs", json={"page_size": 1}, headers=headers
    )
    assert listing.status_code == 200, listing.text
    assert listing.json()["total_count"] == 2
    assert listing.json()["page_info"]["has_next_page"] is True
    end = listing.json()["page_info"]["end_cursor"]
    page = await client.post(
        "/api/internal/host/graphs",
        json={"page_size": 1, "cursor": end},
        headers=headers,
    )
    assert {
        listing.json()["items"][0]["node_id"],
        page.json()["items"][0]["node_id"],
    } == {root, second}
    for body in ({"cursor": -1}, {"page_size": 201}, {"owner_user_id": "bad"}):
        assert (
            await client.post("/api/internal/host/graphs", json=body, headers=headers)
        ).status_code == 422
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    summary = await client.get(
        "/api/internal/host/summary", params={"since": since}, headers=headers
    )
    assert summary.status_code == 200, summary.text
    assert summary.json()["total_projects"] == 2
    assert summary.json()["active_projects"] == 2
    assert sum(row["projects"] for row in summary.json()["created_at"]) == 2
    counts = await client.post(
        "/api/internal/host/owners",
        json={"user_ids": [actor, str(uuid4())]},
        headers=headers,
    )
    assert counts.json() == {actor: 2}
    exported = await client.get(
        f"/api/internal/host/graphs/{root}/export",
        params={"actor": actor},
        headers=headers,
    )
    assert exported.status_code == 200, exported.text
    assert exported.json()["root_node_id"] == root
    streamed = await client.post(
        "/api/internal/host/graphs/export-stream",
        params={"actor": actor},
        json={},
        headers=headers,
    )
    assert streamed.status_code == 200, streamed.text
    import json

    assert {
        json.loads(line)["root_node_id"] for line in streamed.text.splitlines()
    } == {root, second}
    dry = await client.post(
        "/api/internal/host/audit/purge?days=7&dry_run=true", headers=headers
    )
    assert dry.status_code == 200, dry.text
    assert dry.json()["would_delete"] == 1
    purged = await client.post("/api/internal/host/audit/purge?days=7", headers=headers)
    assert purged.json()["deleted"] == 1
    monkeypatch.setenv("ATLAS_ADMIN_SERVICE_TOKEN", uuid4().hex)
    assert (
        await client.post("/api/internal/host/graphs", json={}, headers=headers)
    ).status_code == 401
    assert not any(entry["path"].startswith("/api/internal/") for entry in routes())
