"""Repository functions for ``artifacts`` and ``artifact_upload_batches``."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import aiosqlite


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


# ------------------------------------------------------------------
# Artifacts
# ------------------------------------------------------------------

async def create_artifact(
    db: aiosqlite.Connection,
    *,
    artifact_id: str,
    node_id: str,
    artifact_type: str,
    title: str,
    note: str | None = None,
    payload: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    execution_id: str | None = None,
    storage_path: str | None = None,
) -> dict[str, Any]:
    """Insert a new artifact record."""
    now = _now()
    payload_json = json.dumps(payload or {})
    metadata_json = json.dumps(metadata or {})

    await db.execute(
        """
        INSERT INTO artifacts
            (artifact_id, node_id, artifact_type, title, note,
             payload, metadata, execution_id, storage_path, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            artifact_id, node_id, artifact_type, title, note,
            payload_json, metadata_json, execution_id, storage_path, now,
        ),
    )
    await db.commit()
    return {
        "artifact_id": artifact_id,
        "node_id": node_id,
        "artifact_type": artifact_type,
        "title": title,
        "note": note,
        "payload": payload_json,
        "metadata": metadata_json,
        "execution_id": execution_id,
        "storage_path": storage_path,
        "created_at": now,
    }


async def get_artifact(
    db: aiosqlite.Connection,
    artifact_id: str,
) -> dict[str, Any] | None:
    """Return a single artifact or ``None``."""
    cursor = await db.execute(
        "SELECT * FROM artifacts WHERE artifact_id = ?",
        (artifact_id,),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def list_artifacts(
    db: aiosqlite.Connection,
    node_id: str,
) -> list[dict[str, Any]]:
    """Return all artifacts belonging to a node, newest first."""
    cursor = await db.execute(
        "SELECT * FROM artifacts WHERE node_id = ? ORDER BY created_at DESC",
        (node_id,),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def delete_artifact(
    db: aiosqlite.Connection,
    artifact_id: str,
) -> bool:
    """Delete an artifact. Returns ``True`` if a row was removed."""
    cursor = await db.execute(
        "DELETE FROM artifacts WHERE artifact_id = ?",
        (artifact_id,),
    )
    await db.commit()
    return cursor.rowcount > 0


async def update_note(
    db: aiosqlite.Connection,
    artifact_id: str,
    note: str | None,
) -> dict[str, Any] | None:
    """Update the note field on an artifact."""
    cursor = await db.execute(
        "UPDATE artifacts SET note = ? WHERE artifact_id = ?",
        (note, artifact_id),
    )
    await db.commit()
    if cursor.rowcount == 0:
        return None
    return await get_artifact(db, artifact_id)


async def update_artifact_node(db, artifact_id: str, new_node_id: str) -> bool:
    """Re-pin an artifact to a different node. Returns True if a row changed."""
    cursor = await db.execute(
        "UPDATE artifacts SET node_id = ? WHERE artifact_id = ?",
        (new_node_id, artifact_id),
    )
    await db.commit()
    return (cursor.rowcount or 0) > 0


# ------------------------------------------------------------------
# Upload batches
# ------------------------------------------------------------------

async def create_upload_batch(
    db: aiosqlite.Connection,
    *,
    batch_token: str,
    node_id: str,
    expected_revision: int,
    items: list[dict[str, Any]],
    expires_at: str,
) -> dict[str, Any]:
    """Insert an upload batch record."""
    now = _now()
    items_json = json.dumps(items)
    await db.execute(
        """
        INSERT INTO artifact_upload_batches
            (batch_token, node_id, expected_revision, items, expires_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (batch_token, node_id, expected_revision, items_json, expires_at, now),
    )
    await db.commit()
    return {
        "batch_token": batch_token,
        "node_id": node_id,
        "expected_revision": expected_revision,
        "items": items_json,
        "expires_at": expires_at,
        "created_at": now,
    }


async def get_upload_batch(
    db: aiosqlite.Connection,
    batch_token: str,
) -> dict[str, Any] | None:
    """Return an upload batch by token, or ``None``."""
    cursor = await db.execute(
        "SELECT * FROM artifact_upload_batches WHERE batch_token = ?",
        (batch_token,),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def delete_upload_batch(
    db: aiosqlite.Connection,
    batch_token: str,
) -> bool:
    """Delete an upload batch. Returns ``True`` if a row was removed."""
    cursor = await db.execute(
        "DELETE FROM artifact_upload_batches WHERE batch_token = ?",
        (batch_token,),
    )
    await db.commit()
    return cursor.rowcount > 0
