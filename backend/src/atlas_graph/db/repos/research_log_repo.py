"""Repository for the ``research_log`` table.

The research log is append-only and mirrored to ``research_log.jsonl`` on
the project volume. This module is the DB side; the volume mirror is
written by ``app.services.research_log_service.append``.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def insert(
    db,
    *,
    project_id: str,
    entry_type: str,
    title: str,
    body: str | None = None,
    refs: list[dict[str, Any]] | None = None,
    created_by: str,
) -> dict[str, Any]:
    entry_id = str(uuid.uuid4())
    created_at = _now()
    refs_json = json.dumps(refs or [])
    await db.execute(
        """
        INSERT INTO research_log
            (entry_id, project_id, entry_type, title, body, refs, created_at, created_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (entry_id, project_id, entry_type, title, body, refs_json, created_at, created_by),
    )
    await db.commit()
    return {
        "entry_id": entry_id,
        "project_id": project_id,
        "entry_type": entry_type,
        "title": title,
        "body": body,
        "refs": refs or [],
        "created_at": created_at,
        "created_by": created_by,
    }


async def list_entries(
    db,
    *,
    project_id: str,
    entry_types: list[str] | None = None,
    since: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Most-recent-first slice of the research log.

    ``since`` (ISO timestamp) restricts to entries created strictly after
    that moment. ``entry_types`` restricts to the union of the given types.
    """
    sql = "SELECT * FROM research_log WHERE project_id = ?"
    params: list[Any] = [project_id]
    if since:
        sql += " AND created_at > ?"
        params.append(since)
    if entry_types:
        placeholders = ",".join("?" for _ in entry_types)
        sql += f" AND entry_type IN ({placeholders})"
        params.extend(entry_types)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(max(1, min(limit, 500)))

    cursor = await db.execute(sql, tuple(params))
    try:
        rows = await cursor.fetchall()
    finally:
        await cursor.close()
    return [_row_to_entry(r) for r in rows]


async def search(
    db,
    *,
    project_id: str,
    query: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Substring search over title + body (case-insensitive LIKE).

    Good enough for brain-facing recall; a vector index can come later if
    query volume warrants it.
    """
    q = f"%{query}%"
    cursor = await db.execute(
        """
        SELECT * FROM research_log
        WHERE project_id = ?
          AND (LOWER(title) LIKE LOWER(?) OR LOWER(COALESCE(body, '')) LIKE LOWER(?))
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (project_id, q, q, max(1, min(limit, 200))),
    )
    try:
        rows = await cursor.fetchall()
    finally:
        await cursor.close()
    return [_row_to_entry(r) for r in rows]


async def count(
    db, *, project_id: str, entry_type: str | None = None
) -> int:
    sql = "SELECT COUNT(*) AS n FROM research_log WHERE project_id = ?"
    params: list[Any] = [project_id]
    if entry_type:
        sql += " AND entry_type = ?"
        params.append(entry_type)
    cursor = await db.execute(sql, tuple(params))
    try:
        row = await cursor.fetchone()
    finally:
        await cursor.close()
    if row is None:
        return 0
    # aiosqlite row behaves like a dict-or-tuple depending on row_factory
    return int(row["n"]) if hasattr(row, "keys") else int(row[0])


def _row_to_entry(row) -> dict[str, Any]:
    d = dict(row)
    refs_raw = d.get("refs")
    if isinstance(refs_raw, str):
        try:
            refs = json.loads(refs_raw)
        except Exception:
            refs = []
    else:
        refs = refs_raw or []
    return {
        "entry_id": d.get("entry_id"),
        "project_id": d.get("project_id"),
        "entry_type": d.get("entry_type"),
        "title": d.get("title"),
        "body": d.get("body"),
        "refs": refs,
        "created_at": d.get("created_at"),
        "created_by": d.get("created_by"),
    }
