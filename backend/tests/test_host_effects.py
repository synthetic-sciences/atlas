from datetime import datetime, timezone
from uuid import uuid4

from atlas_graph.db.connection import get_db
from atlas_graph.db.repos import access_repo
from atlas_graph.runtime import Host, configure


async def test_host_graph_effects_keep_actor_acl_and_current_collaboration_policy(
    client, monkeypatch
):
    project = (
        await client.post("/api/v1/projects", json={"title": "Remote effects"})
    ).json()["project_id"]
    viewer, stranger = str(uuid4()), str(uuid4())
    async with get_db() as db:
        owner = (
            await (
                await db.execute(
                    "SELECT owner_user_id FROM nodes WHERE node_id=?", (project,)
                )
            ).fetchone()
        )[0]
        now = datetime.now(timezone.utc).isoformat()
        for actor in (viewer, stranger):
            await db.execute(
                "INSERT INTO users (user_id,email,created_at,updated_at) VALUES (?,?,?,?)",
                (actor, f"{actor}@atlas.invalid", now, now),
            )
        await db.commit()
        await access_repo.set_access_rule(
            db, node_id=project, user_id=viewer, access_level="USER"
        )
    token = uuid4().hex
    monkeypatch.setenv("ATLAS_MODE", "hosted")
    monkeypatch.setenv("ATLAS_SIGNING_SECRET", uuid4().hex)
    monkeypatch.setenv("ATLAS_ADMIN_SERVICE_TOKEN", token)
    headers = {"X-Atlas-Admin-Key": token}
    permission = {"allowed": True, "calls": []}

    async def collaboration(db, actor):
        permission["calls"].append(actor)
        return permission["allowed"]

    configure(Host(collaboration=collaboration))
    try:
        body = {"actor": viewer, "node_id": project, "require": "view"}
        assert (
            await client.post("/api/internal/host/graph-access", json=body)
        ).status_code == 401
        assert (
            await client.post(
                "/api/internal/host/graph-access", json=body, headers=headers
            )
        ).json() == {"allowed": True}
        denied = await client.post(
            "/api/internal/host/graph-access",
            json={**body, "actor": stranger},
            headers=headers,
        )
        assert denied.json() == {"allowed": False}
        missing = await client.post(
            "/api/internal/host/graph-access",
            json={**body, "node_id": str(uuid4())},
            headers=headers,
        )
        assert missing.json() == {"allowed": None}
        entry = {
            "actor": viewer,
            "project_id": project,
            "entry_type": "web_search",
            "title": "Provenance",
            "body": "Graph-owned log",
            "refs": [],
        }
        assert (
            await client.post(
                "/api/internal/host/research-log", json=entry, headers=headers
            )
        ).json() == {"appended": False}
        async with get_db() as db:
            await access_repo.set_access_rule(
                db, node_id=project, user_id=viewer, access_level="USER_WRITE"
            )
        written = await client.post(
            "/api/internal/host/research-log", json=entry, headers=headers
        )
        assert written.status_code == 200, written.text
        assert written.json()["appended"] is True
        assert written.json()["entry"]["created_by"] == viewer
        permission["allowed"] = False
        assert (
            await client.post(
                "/api/internal/host/research-log", json=entry, headers=headers
            )
        ).json() == {"appended": False}
        async with get_db() as db:
            await access_repo.remove_access_rule(db, project, viewer)
        assert (
            await client.post(
                "/api/internal/host/graph-access", json=body, headers=headers
            )
        ).json() == {"allowed": False}
        assert (
            await client.post(
                "/api/internal/host/research-log", json=entry, headers=headers
            )
        ).json() == {"appended": False}
        async with get_db() as db:
            assert (
                await (
                    await db.execute(
                        "SELECT COUNT(*) FROM research_log WHERE project_id=? AND entry_type='web_search'",
                        (project,),
                    )
                ).fetchone()
            )[0] == 1
        assert permission["calls"] and all(
            actor == owner for actor in permission["calls"]
        )
    finally:
        configure(Host())


async def test_host_project_mounts_require_graph_access_and_confine_files(client, tmp_path, monkeypatch):
    import json
    from pathlib import Path
    project = (await client.post("/api/v1/projects", json={"title": "Mounted project"})).json()["project_id"]
    async with get_db() as db:
        owner = (await db.execute_fetchall("SELECT owner_user_id FROM nodes WHERE node_id=?", (project,)))[0][0]
    monkeypatch.setenv("ATLAS_MODE", "hosted")
    monkeypatch.setenv("ATLAS_ADMIN_SERVICE_TOKEN", uuid4().hex)
    monkeypatch.setenv("FS_VOLUME_ROOT", str(tmp_path / "mounts"))
    headers = {"X-Atlas-Admin-Key": __import__('os').environ["ATLAS_ADMIN_SERVICE_TOKEN"]}
    endpoint = "/api/internal/host/project-mount"
    body = {"actor": owner, "project_id": project, "path": "skills/private/procedure", "operation": "put", "markdown": "# Mounted only on the graph volume", "manifest": json.dumps({"name": "Procedure"})}
    assert (await client.post(endpoint, json=body)).status_code == 401
    assert (await client.post(endpoint, json={**body,"actor": str(uuid4())}, headers=headers)).status_code == 403
    written = await client.post(endpoint, json=body, headers=headers)
    assert written.status_code == 200, written.text
    assert written.json() == {"path": "skills/private/procedure/SKILL.md"}
    assert (await client.post(endpoint, json=body, headers=headers)).status_code == 200
    read = await client.post(endpoint, json={**body,"operation":"read"}, headers=headers)
    assert read.json() == {"body": body["markdown"]}
    directory = tmp_path / "mounts" / "projects" / project / "skills/private/procedure"
    (directory / "user-note.md").write_text("Keep user data")
    assert (await client.post(endpoint, json={**body,"operation":"remove"}, headers=headers)).status_code == 200
    assert (directory / "user-note.md").read_text() == "Keep user data"
    assert not (directory / "SKILL.md").exists()
    assert (await client.post(endpoint, json={**body,"path":"skills/../../../escape"}, headers=headers)).status_code == 422
    (directory / "SKILL.md").symlink_to(tmp_path / "outside")
    assert (await client.post(endpoint, json={**body,"operation":"read"}, headers=headers)).status_code == 422
    assert (await client.post(endpoint, json={**body,"project_id": str(uuid4())}, headers=headers)).status_code == 404
