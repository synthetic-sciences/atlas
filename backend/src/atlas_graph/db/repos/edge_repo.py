"""Repository functions for the ``node_edges`` table (DAG management).

Includes a recursive-CTE cycle detector to keep the graph acyclic.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import aiosqlite


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


async def has_cycle(
    db: aiosqlite.Connection,
    parent_id: str,
    child_id: str,
) -> bool:
    """Return ``True`` if adding an edge parent_id -> child_id would create a
    cycle.

    A cycle exists when *parent_id* is reachable from *child_id* by
    following existing edges downward. For example, with A -> B -> C,
    adding C -> A is illegal because C is already reachable from A.

    Seed the recursive CTE from ``node_edges`` instead of a raw placeholder so
    Postgres infers ``reachable.node_id`` as UUID while SQLite still compares
    text IDs correctly.
    """
    cursor = await db.execute(
        """
        WITH RECURSIVE reachable AS (
            SELECT e.child_id AS node_id
            FROM node_edges e
            WHERE e.parent_id = ?
            UNION
            SELECT e.child_id
            FROM node_edges e
            JOIN reachable r ON e.parent_id = r.node_id
        )
        SELECT 1 FROM reachable WHERE node_id = ? LIMIT 1
        """,
        (child_id, parent_id),
    )
    row = await cursor.fetchone()
    return row is not None


async def add_edge(
    db: aiosqlite.Connection,
    parent_id: str,
    child_id: str,
    created_at: str | None = None,
) -> dict[str, Any] | None:
    """Insert a new edge.

    Returns the edge dict on success, or ``None`` if it would create a
    cycle or the edge already exists.  An optional *created_at* timestamp
    may be provided; otherwise the current time is used.
    """
    if parent_id == child_id:
        return None

    if await has_cycle(db, parent_id, child_id):
        return None

    now = created_at or _now()
    try:
        await db.execute(
            """
            INSERT INTO node_edges (parent_id, child_id, created_at)
            VALUES (?, ?, ?)
            """,
            (parent_id, child_id, now),
        )
        await db.commit()
    except aiosqlite.IntegrityError:
        # UNIQUE constraint - edge already exists
        return None

    return {
        "parent_id": parent_id,
        "child_id": child_id,
        "created_at": now,
    }


async def remove_edge(
    db: aiosqlite.Connection,
    parent_id: str,
    child_id: str,
) -> bool:
    """Remove an edge. Returns ``True`` if a row was deleted."""
    cursor = await db.execute(
        "DELETE FROM node_edges WHERE parent_id = ? AND child_id = ?",
        (parent_id, child_id),
    )
    await db.commit()
    return cursor.rowcount > 0


async def get_parents(
    db: aiosqlite.Connection,
    child_id: str,
) -> list[str]:
    """Return the node IDs of all parents of *child_id*."""
    cursor = await db.execute(
        """
        SELECT e.parent_id FROM node_edges e
        WHERE e.child_id = ?
        ORDER BY e.created_at ASC
        """,
        (child_id,),
    )
    rows = await cursor.fetchall()
    return [r[0] for r in rows]


async def get_children(
    db: aiosqlite.Connection,
    parent_id: str,
) -> list[str]:
    """Return the node IDs of all children of *parent_id*."""
    cursor = await db.execute(
        """
        SELECT e.child_id FROM node_edges e
        WHERE e.parent_id = ?
        ORDER BY e.created_at ASC
        """,
        (parent_id,),
    )
    rows = await cursor.fetchall()
    return [r[0] for r in rows]


async def get_edges_for_nodes(
    db,
    node_ids: list[str],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Batch-fetch all edges involving any of the given node_ids.

    Returns (parents_map, children_map) where:
      parents_map[child_id] = [parent_id, ...]
      children_map[parent_id] = [child_id, ...]
    """
    if not node_ids:
        return {}, {}

    placeholders = ",".join("?" for _ in node_ids)
    cursor = await db.execute(
        f"""
        SELECT parent_id, child_id FROM node_edges
        WHERE parent_id IN ({placeholders}) OR child_id IN ({placeholders})
        ORDER BY created_at ASC
        """,
        list(node_ids) + list(node_ids),
    )
    rows = await cursor.fetchall()

    from collections import defaultdict
    parents_map: dict[str, list[str]] = defaultdict(list)
    children_map: dict[str, list[str]] = defaultdict(list)

    for row in rows:
        parent_id, child_id = row[0], row[1]
        parents_map[child_id].append(parent_id)
        children_map[parent_id].append(child_id)

    return dict(parents_map), dict(children_map)
