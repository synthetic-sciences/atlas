"""Deterministic project-root operations for Atlas clients.

Projects are graph roots. This module deliberately contains no hosted agent,
model execution, or managed-compute behavior.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import aiosqlite
from fastapi import HTTPException

from atlas_graph.models.node import StageNodeCreateRequest
from atlas_graph.services import node_service, research_log_service


_DEDUPE_MARKER_PREFIX = "atlas-project-dedupe:"


def _dedupe_marker(key: str) -> str:
    return _DEDUPE_MARKER_PREFIX + key.strip()


def _dedupe_conflict(key: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "project_dedupe_conflict",
            "message": message,
            "dedupe_key": key,
        },
    )


_SQLITE_TRANSACTION = object()


async def _begin_write(
    db: aiosqlite.Connection,
    *,
    isolation: str = "serializable",
):
    """Start a real write transaction on SQLite and PgConnectionWrapper."""
    raw = getattr(db, "raw", None)
    if raw is not None:
        transaction = raw.transaction(isolation=isolation)
        await transaction.start()
        return transaction
    await db.execute("BEGIN IMMEDIATE")
    return _SQLITE_TRANSACTION


async def _commit_write(db: aiosqlite.Connection, transaction) -> None:
    if transaction is _SQLITE_TRANSACTION:
        await db.commit()
    else:
        await transaction.commit()


async def _rollback_write(db: aiosqlite.Connection, transaction) -> None:
    if transaction is _SQLITE_TRANSACTION:
        await db.rollback()
    else:
        await transaction.rollback()


async def _lock_dedupe_markers(
    db: aiosqlite.Connection,
    *,
    user_id: str,
    markers: list[str],
) -> None:
    """Serialize marker creation, repair, deletion, and explicit merge on PG.

    SQLite's ``BEGIN IMMEDIATE`` already serializes writers. PostgreSQL uses
    the same transaction-scoped advisory-lock expression as the node triggers,
    including for absent registry rows that cannot be protected by FOR UPDATE.
    """
    if getattr(db, "raw", None) is None:
        return
    for marker in sorted(set(markers)):
        await db.execute(
            "SELECT pg_advisory_xact_lock("
            "hashtextextended(? || ':' || ?, 0))",
            (user_id, marker),
        )
    if markers:
        placeholders = ",".join("?" for _ in markers)
        cursor = await db.execute(
            "SELECT project_id FROM project_dedupe_keys "
            f"WHERE owner_user_id = ? AND dedupe_marker IN ({placeholders}) "
            "ORDER BY dedupe_marker FOR UPDATE",
            [user_id, *markers],
        )
        await cursor.fetchall()
        await cursor.close()


async def _find_by_dedupe_key(
    db: aiosqlite.Connection,
    *,
    user_id: str,
    key: str,
) -> dict[str, Any] | None:
    marker = _dedupe_marker(key)
    # READ COMMITTED is deliberate: PostgreSQL fixes a SERIALIZABLE snapshot
    # when the advisory-lock SELECT starts, before a conflicting delete has
    # necessarily committed. Once that lock wait ends, the node/registry reads
    # below must take a fresh snapshot or they can repair a claim from stale
    # pre-delete state. SQLite still uses BEGIN IMMEDIATE.
    transaction = await _begin_write(db, isolation="read_committed")
    try:
        await _lock_dedupe_markers(db, user_id=user_id, markers=[marker])
        cursor = await db.execute(
            "SELECT node_id FROM nodes "
            "WHERE owner_user_id = ? AND external_transcript_ref = ? "
            "ORDER BY created_at ASC, node_id ASC LIMIT 2",
            (user_id, marker),
        )
        try:
            rows = await cursor.fetchall()
        finally:
            await cursor.close()

        # Older releases performed a check followed by an unrelated insert, so
        # a small number of databases may already contain duplicate roots.
        # Never choose one based on query planning; preserve both and fail closed.
        if len(rows) > 1:
            raise _dedupe_conflict(
                key,
                "Multiple projects already use this dedupe key. Merge them before retrying.",
            )

        cursor = await db.execute(
            "SELECT project_id FROM project_dedupe_keys "
            "WHERE owner_user_id = ? AND dedupe_marker = ?",
            (user_id, marker),
        )
        try:
            registry_row = await cursor.fetchone()
        finally:
            await cursor.close()

        if not rows:
            if registry_row:
                raise _dedupe_conflict(
                    key,
                    "The project dedupe registry is inconsistent. Retry after support repair.",
                )
            await _commit_write(db, transaction)
            return None

        node_id = rows[0]["node_id"] if hasattr(rows[0], "keys") else rows[0][0]
        if registry_row is None:
            # Repair and the final node recheck share the same serialized
            # transaction, so a concurrent delete cannot leave an orphan claim.
            now = datetime.now(timezone.utc).isoformat()
            await db.execute(
                "INSERT OR IGNORE INTO project_dedupe_keys "
                "(owner_user_id, dedupe_marker, project_id, created_at) "
                "VALUES (?, ?, ?, ?)",
                (user_id, marker, str(node_id), now),
            )
            cursor = await db.execute(
                "SELECT project_id FROM project_dedupe_keys "
                "WHERE owner_user_id = ? AND dedupe_marker = ?",
                (user_id, marker),
            )
            try:
                registry_row = await cursor.fetchone()
            finally:
                await cursor.close()

        authoritative_id = (
            registry_row["project_id"]
            if registry_row is not None and hasattr(registry_row, "keys")
            else registry_row[0] if registry_row is not None else None
        )
        if authoritative_id is None or str(authoritative_id) != str(node_id):
            raise _dedupe_conflict(
                key,
                "The project dedupe registry disagrees with the stored project. Retry after support repair.",
            )

        cursor = await db.execute(
            "SELECT 1 FROM nodes WHERE owner_user_id = ? AND node_id = ? "
            "AND external_transcript_ref = ?",
            (user_id, str(node_id), marker),
        )
        try:
            still_present = await cursor.fetchone()
        finally:
            await cursor.close()
        if still_present is None:
            raise _dedupe_conflict(
                key,
                "The authoritative project changed during lookup. Retry the request.",
            )

        try:
            result = await node_service.get_node(db, user_id, str(node_id))
        except (HTTPException, ValueError):
            raise _dedupe_conflict(
                key,
                "The authoritative project exists but could not be loaded. Retry after support repair.",
            )
        await _commit_write(db, transaction)
        return result
    except Exception:
        try:
            await _rollback_write(db, transaction)
        except Exception:
            pass
        raise


async def list_projects(
    db: aiosqlite.Connection,
    *,
    user_id: str,
    dedupe_key: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    if dedupe_key:
        existing = await _find_by_dedupe_key(
            db,
            user_id=user_id,
            key=dedupe_key,
        )
        if existing is None:
            return {"projects": []}
        return {
            "projects": [
                {
                    "project_id": existing.get("node_id"),
                    "title": existing.get("title"),
                    "repo_url": existing.get("repo_url"),
                    "branch_name": existing.get("branch_name"),
                    "kind": existing.get("kind"),
                    "updated_at": existing.get("updated_at"),
                    "dedupe_key": dedupe_key,
                }
            ]
        }

    response = await node_service.list_nodes(
        db,
        user_id,
        visibility="my_nodes",
        per_page=200,
    )
    nodes = response.get("nodes", []) if isinstance(response, dict) else list(response)
    return {
        "projects": [
            {
                "project_id": node.get("node_id"),
                "title": node.get("title"),
                "repo_url": node.get("repo_url"),
                "branch_name": node.get("branch_name"),
                "kind": node.get("kind"),
                "updated_at": node.get("updated_at"),
            }
            for node in nodes
            if not (node.get("parent_ids") or [])
        ]
    }


async def create_project(
    db: aiosqlite.Connection,
    *,
    user_id: str,
    title: str,
    repo_url: str | None = None,
    branch_name: str | None = None,
    dedupe_key: str | None = None,
) -> dict[str, Any]:
    if dedupe_key:
        existing = await _find_by_dedupe_key(
            db,
            user_id=user_id,
            key=dedupe_key,
        )
        if existing is not None:
            return {
                "project_id": existing.get("node_id"),
                "title": existing.get("title"),
                "repo_url": existing.get("repo_url"),
                "branch_name": existing.get("branch_name"),
                "deduped": True,
                "dedupe_key": dedupe_key,
            }

    normalized_title = (title or "").strip() or "Untitled project"
    try:
        created = await node_service.stage_create(
            db,
            user_id,
            StageNodeCreateRequest(
                title=normalized_title,
                repo_url=repo_url,
                branch_name=branch_name,
                updated_by=user_id,
                external_transcript_ref=(
                    _dedupe_marker(dedupe_key) if dedupe_key else None
                ),
            ),
        )
    except Exception as create_error:
        if not dedupe_key:
            raise
        # The database trigger is the concurrency authority. A racing request
        # can win after our first read and make this INSERT fail. Once that
        # transaction commits, return its root instead of leaking a 500.
        await db.rollback()
        for delay in (0.0, 0.01, 0.05):
            if delay:
                await asyncio.sleep(delay)
            existing = await _find_by_dedupe_key(
                db,
                user_id=user_id,
                key=dedupe_key,
            )
            if existing is not None:
                return {
                    "project_id": existing.get("node_id"),
                    "title": existing.get("title"),
                    "repo_url": existing.get("repo_url"),
                    "branch_name": existing.get("branch_name"),
                    "deduped": True,
                    "dedupe_key": dedupe_key,
                }
        raise create_error
    try:
        await research_log_service.append(
            db,
            project_id=created["node_id"],
            entry_type="project_created",
            title=f"project created: {normalized_title}",
            body=f"repo: {repo_url or '-'} · branch: {branch_name or '-'}",
            created_by=user_id,
        )
    except Exception:
        # The graph root is authoritative; journal mirroring is best effort.
        pass
    return {
        "project_id": created["node_id"],
        "title": created.get("title"),
        "repo_url": created.get("repo_url"),
        "branch_name": created.get("branch_name"),
        "deduped": False,
        "dedupe_key": dedupe_key,
    }


async def merge_projects(
    db: aiosqlite.Connection,
    *,
    user_id: str,
    canonical_id: str,
    duplicate_ids: list[str],
) -> dict[str, Any]:
    if len(set(duplicate_ids)) != len(duplicate_ids):
        raise HTTPException(status_code=400, detail="duplicate_ids must be unique")

    async def _root_or_404(node_id: str, label: str) -> dict[str, Any]:
        try:
            node = await node_service.get_node(db, user_id, node_id)
        except (HTTPException, ValueError):
            node = None
        if not node:
            raise HTTPException(status_code=404, detail=f"{label} not found")
        if node.get("parent_ids"):
            raise HTTPException(status_code=400, detail=f"{label} must be a root project")
        return node

    transaction = await _begin_write(db)
    try:
        requested_ids = sorted({canonical_id, *duplicate_ids})
        placeholders = ",".join("?" for _ in requested_ids)
        lock_suffix = " FOR UPDATE" if getattr(db, "raw", None) is not None else ""
        cursor = await db.execute(
            "SELECT node_id FROM nodes WHERE owner_user_id = ? "
            f"AND node_id IN ({placeholders}) ORDER BY node_id{lock_suffix}",
            [user_id, *requested_ids],
        )
        await cursor.fetchall()
        await cursor.close()

        canonical = await _root_or_404(canonical_id, "canonical project")
        duplicates: list[dict[str, Any]] = []
        for duplicate_id in duplicate_ids:
            if duplicate_id == canonical_id:
                raise HTTPException(
                    status_code=400,
                    detail="canonical_id cannot also be a duplicate_id",
                )
            duplicates.append(
                await _root_or_404(duplicate_id, f"duplicate {duplicate_id}")
            )

        markers = [
            marker
            for node in [canonical, *duplicates]
            if isinstance((marker := node.get("external_transcript_ref")), str)
            and marker.startswith(_DEDUPE_MARKER_PREFIX)
        ]
        await _lock_dedupe_markers(db, user_id=user_id, markers=markers)

        reparented_total = 0
        backfilled_marker: str | None = None
        canonical_has_marker = bool(canonical.get("external_transcript_ref"))
        canonical_marker = canonical.get("external_transcript_ref")
        for duplicate in duplicates:
            duplicate_id = str(duplicate["node_id"])
            marker = duplicate.get("external_transcript_ref")
            if (
                not canonical_has_marker
                and backfilled_marker is None
                and isinstance(marker, str)
                and marker.startswith(_DEDUPE_MARKER_PREFIX)
            ):
                backfilled_marker = marker

            cursor = await db.execute(
                "SELECT child_id FROM node_edges WHERE parent_id = ?",
                (duplicate_id,),
            )
            try:
                children = await cursor.fetchall()
            finally:
                await cursor.close()
            for row in children:
                child_id = row["child_id"] if hasattr(row, "keys") else row[0]
                cursor = await db.execute(
                    "SELECT 1 FROM node_edges "
                    "WHERE parent_id = ? AND child_id = ? LIMIT 1",
                    (canonical_id, child_id),
                )
                try:
                    already_linked = await cursor.fetchone()
                finally:
                    await cursor.close()
                if already_linked:
                    await db.execute(
                        "DELETE FROM node_edges "
                        "WHERE parent_id = ? AND child_id = ?",
                        (duplicate_id, child_id),
                    )
                else:
                    await db.execute(
                        "UPDATE node_edges SET parent_id = ? "
                        "WHERE parent_id = ? AND child_id = ?",
                        (canonical_id, duplicate_id, child_id),
                    )
                    reparented_total += 1

            await db.execute("DELETE FROM node_edges WHERE child_id = ?", (duplicate_id,))
            await db.execute(
                "DELETE FROM nodes WHERE node_id = ? AND owner_user_id = ?",
                (duplicate_id, user_id),
            )

        if backfilled_marker:
            await db.execute(
                "UPDATE nodes SET external_transcript_ref = ? "
                "WHERE node_id = ? AND owner_user_id = ?",
                (backfilled_marker, canonical_id, user_id),
            )
            canonical_marker = backfilled_marker
        if (
            isinstance(canonical_marker, str)
            and canonical_marker.startswith(_DEDUPE_MARKER_PREFIX)
        ):
            # Duplicate legacy groups are deliberately not claimed during
            # schema migration. Explicit merge is the sole destructive repair.
            await db.execute(
                "INSERT OR IGNORE INTO project_dedupe_keys "
                "(owner_user_id, dedupe_marker, project_id, created_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    user_id,
                    canonical_marker,
                    canonical_id,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            await db.execute(
                "UPDATE project_dedupe_keys SET project_id = ? "
                "WHERE owner_user_id = ? AND dedupe_marker = ?",
                (canonical_id, user_id, canonical_marker),
            )

        result = {
            "canonical_id": canonical_id,
            "absorbed": [item["node_id"] for item in duplicates],
            "reparented_edges": reparented_total,
            "deleted_nodes": len(duplicates),
            "backfilled_dedupe_key": backfilled_marker,
        }
        await _commit_write(db, transaction)
        return result
    except Exception:
        try:
            await _rollback_write(db, transaction)
        except Exception:
            pass
        raise
