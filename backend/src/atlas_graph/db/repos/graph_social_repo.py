"""Repository for graph social signals: stars and derived fork counts.

Stars are GitHub-style: a user stars a graph (project root). Fork counts are
derived from ``semantic_data.forked_from`` written by ``atlas fork`` /
import, so no separate table is needed to track them.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def add_star(db, *, root_node_id: str, user_id: str) -> bool:
    """Star a graph root. Idempotent; returns True if a new star was created."""
    cursor = await db.execute(
        "SELECT 1 FROM graph_stars WHERE root_node_id = ? AND user_id = ?",
        (root_node_id, user_id),
    )
    if await cursor.fetchone() is not None:
        return False
    await db.execute(
        "INSERT INTO graph_stars (root_node_id, user_id, created_at) VALUES (?, ?, ?)",
        (root_node_id, user_id, _now()),
    )
    await db.commit()
    return True


async def remove_star(db, *, root_node_id: str, user_id: str) -> bool:
    """Unstar a graph root. Returns True if a star was removed."""
    cursor = await db.execute(
        "DELETE FROM graph_stars WHERE root_node_id = ? AND user_id = ?",
        (root_node_id, user_id),
    )
    await db.commit()
    return cursor.rowcount > 0


async def star_count(db, root_node_id: str) -> int:
    cursor = await db.execute(
        "SELECT COUNT(*) FROM graph_stars WHERE root_node_id = ?",
        (root_node_id,),
    )
    row = await cursor.fetchone()
    return int(row[0]) if row else 0


async def has_starred(db, root_node_id: str, user_id: str | None) -> bool:
    if not user_id or user_id == "__anonymous__":
        return False
    cursor = await db.execute(
        "SELECT 1 FROM graph_stars WHERE root_node_id = ? AND user_id = ?",
        (root_node_id, user_id),
    )
    return await cursor.fetchone() is not None


async def star_counts(db, root_node_ids: list[str]) -> dict[str, int]:
    """Bulk star counts for a set of roots. Empty input → empty map."""
    ids = [r for r in dict.fromkeys(root_node_ids) if r]
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    cursor = await db.execute(
        f"""
        SELECT root_node_id, COUNT(*) AS n
        FROM graph_stars
        WHERE root_node_id IN ({placeholders})
        GROUP BY root_node_id
        """,
        tuple(ids),
    )
    rows = await cursor.fetchall()
    out: dict[str, int] = {}
    for row in rows:
        d = dict(row) if hasattr(row, "keys") else {"root_node_id": row[0], "n": row[1]}
        out[d["root_node_id"]] = int(d["n"])
    return out


async def starred_set(db, root_node_ids: list[str], user_id: str | None) -> set[str]:
    """Which of ``root_node_ids`` the user has starred."""
    if not user_id or user_id == "__anonymous__":
        return set()
    ids = [r for r in dict.fromkeys(root_node_ids) if r]
    if not ids:
        return set()
    placeholders = ",".join("?" for _ in ids)
    cursor = await db.execute(
        f"""
        SELECT root_node_id FROM graph_stars
        WHERE user_id = ? AND root_node_id IN ({placeholders})
        """,
        (user_id, *ids),
    )
    rows = await cursor.fetchall()
    return {(dict(r)["root_node_id"] if hasattr(r, "keys") else r[0]) for r in rows}


async def fork_counts(db, root_node_ids: list[str], *, scan_cap: int = 5000) -> dict[str, int]:
    """Derive fork counts from ``semantic_data.forked_from.node_id``.

    A fork is a graph created by ``atlas fork`` / import; its root stamps
    ``semantic_data.forked_from`` pointing at the source node. We scan nodes
    whose ``semantic_data`` mentions ``forked_from`` (cheap LIKE prefilter)
    and tally by source id in Python — cross-DB safe and bounded by
    ``scan_cap``.
    """
    ids = {r for r in root_node_ids if r}
    if not ids:
        return {}
    # ``semantic_data`` is TEXT on SQLite (dev) but JSONB on Postgres (prod);
    # cast to text so the LIKE prefilter works on both backends.
    cursor = await db.execute(
        """
        SELECT semantic_data FROM nodes
        WHERE semantic_data IS NOT NULL
          AND CAST(semantic_data AS TEXT) LIKE '%forked_from%'
        LIMIT ?
        """,
        (scan_cap,),
    )
    rows = await cursor.fetchall()
    counts: dict[str, int] = {rid: 0 for rid in ids}
    for row in rows:
        raw = dict(row)["semantic_data"] if hasattr(row, "keys") else row[0]
        if not raw:
            continue
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            continue
        forked = data.get("forked_from") if isinstance(data, dict) else None
        source = forked.get("node_id") if isinstance(forked, dict) else None
        if source in counts:
            counts[source] += 1
    return counts


__all__ = [
    "add_star",
    "remove_star",
    "star_count",
    "has_starred",
    "star_counts",
    "starred_set",
    "fork_counts",
]
