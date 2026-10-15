from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4
import sys

import pytest


async def test_graph_lifecycle_without_an_account_service(client):
    created = await client.post("/api/v1/projects", json={"title": "Independent graph", "dedupe_key": "local:experiment"})
    assert created.status_code == 201, created.text
    project = created.json()["project_id"]
    replay = await client.post("/api/v1/projects", json={"title": "Independent graph", "dedupe_key": "local:experiment"})
    assert replay.json()["project_id"] == project
    assert replay.json()["deduped"] is True

    child = await client.post("/api/nodes/stage-create", json={"title": "A hypothesis", "summary": "Recorded evidence", "parent_ids": [project], "kind": "hypothesis", "hypothesis": "A falsifiable claim"})
    assert child.status_code in {200, 201}, child.text
    node = child.json()
    assert node["parent_ids"] == [project]

    updated = await client.post("/api/nodes/stage-update", json={"node_id": node["node_id"], "expected_revision": node["revision"], "outcome": "completed"})
    assert updated.status_code == 200, updated.text
    node = updated.json()

    committed = await client.post("/api/nodes/commit", json={"node_id": node["node_id"], "expected_revision": node["revision"], "summary": "Recorded evidence"})
    assert committed.status_code == 200, committed.text
    current = committed.json()
    assert current["lifecycle"] == "committed"
    assert current["revision"] > node["revision"]

    tree = await client.get(f"/api/nodes/{project}/tree?projection=full")
    assert tree.status_code == 200
    assert {entry["node_id"] for entry in tree.json()["nodes"]} == {project, node["node_id"]}

    export = await client.post("/api/v1/export", json={"node_ids": [project, node["node_id"]]})
    assert export.status_code == 200, export.text
    assert "Independent graph" in export.text


async def test_mutation_replays_and_conflicting_keys(client):
    headers = {"Idempotency-Key": "one-project"}
    first = await client.post("/api/v1/projects", headers=headers, json={"title": "Only once"})
    second = await client.post("/api/v1/projects", headers=headers, json={"title": "Only once"})
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    conflict = await client.post("/api/v1/projects", headers=headers, json={"title": "Different"})
    assert conflict.status_code == 409
    listed = await client.get("/api/v1/projects")
    assert len(listed.json()["projects"]) == 1


async def test_research_log_and_node_history_remain_operational(client):
    created = await client.post("/api/v1/projects", json={"title": "Research log"})
    project = created.json()["project_id"]
    result = await client.post("/api/v1/research/log", json={"project_id": project, "entry_type": "decision", "title": "Keep provenance", "body": "A durable research record"})
    assert result.status_code == 201, result.text
    log = await client.get("/api/v1/research/log", params={"project_id": project})
    assert log.status_code == 200
    assert "Keep provenance" in log.text


@pytest.mark.parametrize("path", ["/api/nodes/explore", "/api/researchers", "/api/users/someone", "/api/competitions", "/api/v1/explore"])
async def test_hidden_public_surfaces_remain_hidden(client, path):
    assert (await client.get(path)).status_code == 404


async def test_authentication_and_local_browser_boundary(client):
    assert (await client.get("/api/v1/projects", headers={"Authorization": "Bearer invalid"})).status_code == 401
    assert (await client.post("/api/v1/projects", headers={"Origin": "https://example.com"}, json={"title": "Cross-origin"})).status_code == 403
    assert (await client.get("/api/v1/projects", headers={"Host": "example.com"})).status_code == 403


async def test_local_graph_acl_does_not_grant_other_principals_access(client):
    from atlas_graph.auth.access_check import check_node_access
    from atlas_graph.db.connection import get_db

    created = await client.post("/api/v1/projects", json={"title": "Private"})
    async with get_db() as db:
        assert await check_node_access(db, str(uuid4()), created.json()["project_id"], "view") is False


async def test_graph_database_has_no_account_or_wallet_tables(client):
    from atlas_graph.db.connection import get_db

    async with get_db() as db:
        cursor = await db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        names = {row[0] for row in await cursor.fetchall()}
    assert {"nodes", "node_edges", "artifacts", "research_log", "project_dedupe_keys"} <= names
    assert not names.intersection({"credit_transactions", "user_subscriptions", "api_keys", "telemetry_events", "organizations", "pending_managed_debits"})


async def test_standalone_does_not_load_dashboard_modules(client):
    assert "app" not in sys.modules
    assert not any(name.startswith("app.") for name in sys.modules)


async def test_author_handles_preserve_case_insensitive_oldest_match(client):
    from atlas_graph.db.connection import get_db
    from atlas_graph.db.repos.user_repo import get_user_by_github_username

    first, second = str(uuid4()), str(uuid4())
    async with get_db() as db:
        for identifier, handle, date in [(second, "researcher", "2026-10-02"), (first, "Researcher", "2026-10-01")]:
            await db.execute(
                "INSERT INTO users (user_id,email,github_username,created_at,updated_at) VALUES (?,?,?,?,?)",
                (identifier, f"{identifier}@example.test", handle, date, date),
            )
        await db.commit()
        assert (await get_user_by_github_username(db, " RESEARCHER "))["user_id"] == first
        assert await get_user_by_github_username(db, " ") is None


async def test_evidence_upload_and_download_without_dashboard(client):
    project = (await client.post("/api/v1/projects", json={"title": "Evidence"})).json()["project_id"]
    node = (await client.get(f"/api/nodes/{project}")).json()
    prepared = await client.post(f"/api/v1/nodes/{project}/artifacts/uploads/prepare", json={"expected_revision": node["revision"], "items": [{"filename": "results.txt", "artifact_type": "text", "title": "Results", "media_type": "text/plain"}]})
    assert prepared.status_code == 201, prepared.text
    body = prepared.json()
    upload = body["items"][0]
    uploaded = await client.put(upload["upload_url"], content=b"results\n", headers={"Content-Type": "text/plain"})
    assert uploaded.status_code in {200, 201, 204}, uploaded.text
    finalized = await client.post(f"/api/v1/nodes/{project}/artifacts/uploads/finalize", json={"batch_token": body["batch_token"]})
    assert finalized.status_code == 200, finalized.text
    artifacts = await client.get(f"/api/v1/nodes/{project}/artifacts")
    assert artifacts.status_code == 200
    assert "Results" in artifacts.text
    files = (await client.get(f"/api/v1/nodes/{project}/files")).json()
    path = files["files"][0]["storage_path"]
    downloaded = await client.get("/api/v1/blobs", params={"storage_path": path})
    assert downloaded.status_code == 200
    assert downloaded.content == b"results\n"

