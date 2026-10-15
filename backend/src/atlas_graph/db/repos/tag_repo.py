"""Repository functions for ``tags``, ``tag_assignments``, and ``tag_history``."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import aiosqlite


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


# ------------------------------------------------------------------
# Tag CRUD
# ------------------------------------------------------------------

async def create_tag(
    db: aiosqlite.Connection,
    *,
    tag_id: str,
    root_node_id: str,
    name: str,
    bg_color: str = "#6366f1",
    text_color: str = "#ffffff",
    one_only: bool = False,
    track_history: bool = False,
) -> dict[str, Any]:
    """Insert a new tag scoped to *root_node_id*."""
    now = _now()
    await db.execute(
        """
        INSERT INTO tags
            (tag_id, root_node_id, name, bg_color, text_color,
             one_only, track_history, history_next_index, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
        """,
        (
            tag_id, root_node_id, name, bg_color, text_color,
            one_only, track_history, now, now,
        ),
    )
    await db.commit()
    return {
        "tag_id": tag_id,
        "root_node_id": root_node_id,
        "name": name,
        "bg_color": bg_color,
        "text_color": text_color,
        "one_only": one_only,
        "track_history": track_history,
        "history_next_index": 0,
        "created_at": now,
        "updated_at": now,
    }


async def update_tag(
    db: aiosqlite.Connection,
    tag_id: str,
    **fields: Any,
) -> dict[str, Any] | None:
    """Update mutable columns on a tag.  Returns the updated row or ``None``."""
    if not fields:
        return await _get_tag(db, tag_id)

    fields["updated_at"] = _now()

    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [tag_id]

    cursor = await db.execute(
        f"UPDATE tags SET {set_clause} WHERE tag_id = ?",
        values,
    )
    await db.commit()
    if cursor.rowcount == 0:
        return None
    return await _get_tag(db, tag_id)


async def delete_tag(
    db: aiosqlite.Connection,
    tag_id: str,
) -> bool:
    """Delete a tag (cascading to assignments and history via FK). Returns
    ``True`` if the tag existed."""
    cursor = await db.execute(
        "DELETE FROM tags WHERE tag_id = ?",
        (tag_id,),
    )
    await db.commit()
    return cursor.rowcount > 0


async def get_tags_for_root(
    db: aiosqlite.Connection,
    root_node_id: str,
) -> list[dict[str, Any]]:
    """Return all tags scoped to a given root node."""
    cursor = await db.execute(
        "SELECT * FROM tags WHERE root_node_id = ? ORDER BY created_at ASC",
        (root_node_id,),
    )
    rows = await cursor.fetchall()
    result = []
    for r in rows:
        d = dict(r)
        # SQLite stores booleans as 1/0 -- coerce to Python bools.
        d["one_only"] = bool(d.get("one_only", 0))
        d["track_history"] = bool(d.get("track_history", 0))
        result.append(d)
    return result


# ------------------------------------------------------------------
# Tag assignments
# ------------------------------------------------------------------

async def get_tag_assignments(
    db: aiosqlite.Connection,
    node_id: str,
) -> list[dict[str, Any]]:
    """Return all tag assignments for a given node."""
    cursor = await db.execute(
        "SELECT * FROM tag_assignments WHERE node_id = ? ORDER BY created_at ASC",
        (node_id,),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def set_tag_assignments(
    db: aiosqlite.Connection,
    node_id: str,
    tag_ids: list[str],
) -> list[dict[str, Any]]:
    """Replace the full set of tag assignments for *node_id*.

    For any tag marked ``one_only``, existing assignments on *other* nodes
    are removed first.  If the tag also has ``track_history`` enabled, a
    history entry is written before removing the old assignment.

    Returns the new list of assignments for the node.
    """
    now = _now()

    # Fetch tag metadata for the supplied tag_ids so we know which are
    # one_only / track_history.
    if tag_ids:
        placeholders = ", ".join("?" for _ in tag_ids)
        cursor = await db.execute(
            f"SELECT * FROM tags WHERE tag_id IN ({placeholders})",
            tag_ids,
        )
        tag_rows = {row["tag_id"]: dict(row) for row in await cursor.fetchall()}
    else:
        tag_rows = {}

    # Handle one_only eviction + history for each incoming tag.
    for tid in tag_ids:
        tag_meta = tag_rows.get(tid)
        if tag_meta is None:
            continue

        if tag_meta["one_only"]:
            # Find the node that currently holds this tag (if any).
            cur = await db.execute(
                """
                SELECT ta.node_id FROM tag_assignments ta
                WHERE ta.tag_id = ? AND ta.node_id != ?
                """,
                (tid, node_id),
            )
            old_rows = await cur.fetchall()

            for old_row in old_rows:
                old_node_id = old_row["node_id"]

                if tag_meta["track_history"]:
                    history_index = tag_meta["history_next_index"]
                    await db.execute(
                        """
                        INSERT INTO tag_history
                            (tag_id, node_id, history_index,
                             superseded_at, superseded_by_node_id)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (tid, old_node_id, history_index, now, node_id),
                    )
                    await db.execute(
                        """
                        UPDATE tags SET history_next_index = ?, updated_at = ?
                        WHERE tag_id = ?
                        """,
                        (history_index + 1, now, tid),
                    )

                # Remove the old assignment.
                await db.execute(
                    "DELETE FROM tag_assignments WHERE tag_id = ? AND node_id = ?",
                    (tid, old_node_id),
                )

    # Remove all current assignments for this node.
    await db.execute(
        "DELETE FROM tag_assignments WHERE node_id = ?",
        (node_id,),
    )

    # Insert fresh assignments.
    for tid in tag_ids:
        await db.execute(
            """
            INSERT OR IGNORE INTO tag_assignments (tag_id, node_id, created_at)
            VALUES (?, ?, ?)
            """,
            (tid, node_id, now),
        )

    await db.commit()
    return await get_tag_assignments(db, node_id)


# ------------------------------------------------------------------
# Tag history queries
# ------------------------------------------------------------------

async def get_tag_history_for_node(
    db: aiosqlite.Connection,
    node_id: str,
) -> list[dict[str, Any]]:
    """Return all tag_history entries where this node was superseded
    (i.e. lost a one_only tag to another node)."""
    cursor = await db.execute(
        """
        SELECT tag_id, history_index, superseded_at, superseded_by_node_id
        FROM tag_history
        WHERE node_id = ?
        ORDER BY history_index ASC
        """,
        (node_id,),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

async def _get_tag(
    db: aiosqlite.Connection,
    tag_id: str,
) -> dict[str, Any] | None:
    cursor = await db.execute(
        "SELECT * FROM tags WHERE tag_id = ?",
        (tag_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    d = dict(row)
    d["one_only"] = bool(d.get("one_only", 0))
    d["track_history"] = bool(d.get("track_history", 0))
    return d
