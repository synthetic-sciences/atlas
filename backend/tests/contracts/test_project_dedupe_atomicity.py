from __future__ import annotations

import asyncio

import aiosqlite
import pytest

from atlas_graph.db.connection import get_db
from atlas_graph.db.repos import node_repo
from atlas_graph.models.node import StageNodeCreateRequest
from atlas_graph.services import node_service, project_state_service


@pytest.mark.asyncio
async def test_explicit_duplicate_merge_rolls_back_every_write_on_failure(
    client, auth_headers
):
    user_id = auth_headers["X-Test-User-Id"]
    async with get_db() as db:
        canonical = await project_state_service.create_project(
            db, user_id=user_id, title="Canonical"
        )
        duplicate = await project_state_service.create_project(
            db,
            user_id=user_id,
            title="Legacy duplicate",
            dedupe_key="rollback-merge",
        )
        child = await node_service.stage_create(
            db,
            user_id,
            StageNodeCreateRequest(
                title="Duplicate child",
                parent_ids=[duplicate["project_id"]],
                updated_by=user_id,
            ),
        )
        await db.execute(
            "CREATE TRIGGER fail_project_merge_registry_update "
            "BEFORE UPDATE ON project_dedupe_keys BEGIN "
            "SELECT RAISE(ABORT, 'forced_merge_failure'); END"
        )
        await db.commit()

        with pytest.raises(aiosqlite.IntegrityError, match="forced_merge_failure"):
            await project_state_service.merge_projects(
                db,
                user_id=user_id,
                canonical_id=canonical["project_id"],
                duplicate_ids=[duplicate["project_id"]],
            )

        duplicate_row = await db.execute_fetchall(
            "SELECT node_id,external_transcript_ref FROM nodes WHERE node_id=?",
            (duplicate["project_id"],),
        )
        canonical_row = await db.execute_fetchall(
            "SELECT external_transcript_ref FROM nodes WHERE node_id=?",
            (canonical["project_id"],),
        )
        original_edge = await db.execute_fetchall(
            "SELECT 1 FROM node_edges WHERE parent_id=? AND child_id=?",
            (duplicate["project_id"], child["node_id"]),
        )
        moved_edge = await db.execute_fetchall(
            "SELECT 1 FROM node_edges WHERE parent_id=? AND child_id=?",
            (canonical["project_id"], child["node_id"]),
        )
        registry = await db.execute_fetchall(
            "SELECT project_id FROM project_dedupe_keys "
            "WHERE owner_user_id=? AND dedupe_marker=?",
            (user_id, "atlas-project-dedupe:rollback-merge"),
        )

    assert len(duplicate_row) == 1
    assert duplicate_row[0]["external_transcript_ref"] == (
        "atlas-project-dedupe:rollback-merge"
    )
    assert canonical_row[0]["external_transcript_ref"] is None
    assert len(original_edge) == 1
    assert moved_edge == []
    assert [row["project_id"] for row in registry] == [duplicate["project_id"]]


@pytest.mark.asyncio
async def test_delete_cannot_leave_orphan_dedupe_repair(
    client, auth_headers, monkeypatch
):
    user_id = auth_headers["X-Test-User-Id"]
    dedupe_key = "delete-repair-race"
    marker = "atlas-project-dedupe:" + dedupe_key
    async with get_db() as db:
        created = await project_state_service.create_project(
            db,
            user_id=user_id,
            title="Soon deleted",
            dedupe_key=dedupe_key,
        )
        await db.execute(
            "DELETE FROM project_dedupe_keys "
            "WHERE owner_user_id=? AND dedupe_marker=?",
            (user_id, marker),
        )
        await db.commit()

    lookup_started = asyncio.Event()
    release_lookup = asyncio.Event()
    original_get_node = project_state_service.node_service.get_node

    async def delayed_get_node(*args, **kwargs):
        result = await original_get_node(*args, **kwargs)
        lookup_started.set()
        await release_lookup.wait()
        return result

    monkeypatch.setattr(
        project_state_service.node_service, "get_node", delayed_get_node
    )

    async def lookup():
        async with get_db() as db:
            return await project_state_service.list_projects(
                db, user_id=user_id, dedupe_key=dedupe_key
            )

    async def delete():
        async with get_db() as db:
            return await node_repo.delete_node(db, created["project_id"])

    lookup_task = asyncio.create_task(lookup())
    await asyncio.wait_for(lookup_started.wait(), timeout=2)
    delete_task = asyncio.create_task(delete())
    await asyncio.sleep(0.05)
    assert not delete_task.done()

    release_lookup.set()
    looked_up, deleted = await asyncio.gather(lookup_task, delete_task)
    assert looked_up["projects"][0]["project_id"] == created["project_id"]
    assert deleted is True

    async with get_db() as db:
        nodes = await db.execute_fetchall(
            "SELECT node_id FROM nodes WHERE node_id=?", (created["project_id"],)
        )
        registry = await db.execute_fetchall(
            "SELECT project_id FROM project_dedupe_keys "
            "WHERE owner_user_id=? AND dedupe_marker=?",
            (user_id, marker),
        )
    assert nodes == []
    assert registry == []
