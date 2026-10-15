"""Repository functions for the ``nodes`` table.

Includes recursive CTE helpers for tree traversal, ancestry lookups, and
finding the root node of a sub-graph.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import aiosqlite


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


# ------------------------------------------------------------------
# CRUD
# ------------------------------------------------------------------

async def create_node(
    db: aiosqlite.Connection,
    data: dict[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Insert a new node and return it as a dict.

    Accepts either a single *data* dict **or** keyword arguments.  Extra
    keys such as ``revision``, ``created_at``, and ``updated_at`` in the
    dict are silently ignored -- the repo always inserts revision=0 and
    generates its own timestamps.
    """
    fields = {**(data or {}), **kwargs}

    node_id = fields["node_id"]
    owner_user_id = fields["owner_user_id"]
    slug_name = fields.get("slug_name")
    title = fields.get("title")
    summary = fields.get("summary")
    content = fields.get("content")
    node_type = fields.get("node_type", "untyped")
    lifecycle = fields.get("lifecycle", "staged")
    outcome = fields.get("outcome")
    hypothesis = fields.get("hypothesis")
    no_artifacts_reason = fields.get("no_artifacts_reason")
    insights_raw = fields.get("insights")
    repo_url = fields.get("repo_url")
    branch_name = fields.get("branch_name")
    head_commit_sha = fields.get("head_commit_sha")
    origin_host = fields.get("origin_host")
    updated_by = fields.get("updated_by")
    external_transcript_ref = fields.get("external_transcript_ref")
    sharing_mode = fields.get("sharing_mode", "private")

    now = _now()

    # Normalise insights: accept a JSON string or a list.
    if isinstance(insights_raw, str):
        insights_json = insights_raw
    else:
        insights_json = json.dumps(insights_raw or [])

    await db.execute(
        """
        INSERT INTO nodes (
            node_id, owner_user_id, slug_name, title, summary, content,
            node_type, lifecycle, outcome, hypothesis, no_artifacts_reason,
            insights, repo_url, branch_name, head_commit_sha, origin_host,
            updated_by, external_transcript_ref, revision, sharing_mode,
            created_at, updated_at
        ) VALUES (
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, 0, ?,
            ?, ?
        )
        """,
        (
            node_id, owner_user_id, slug_name, title, summary, content,
            node_type, lifecycle, outcome, hypothesis, no_artifacts_reason,
            insights_json, repo_url, branch_name, head_commit_sha, origin_host,
            updated_by, external_transcript_ref, sharing_mode,
            now, now,
        ),
    )
    await db.commit()
    return await get_node(db, node_id)  # type: ignore[return-value]


async def get_node(
    db: aiosqlite.Connection,
    node_id: str,
) -> dict[str, Any] | None:
    """Return a single node by primary key, or ``None``."""
    cursor = await db.execute(
        "SELECT * FROM nodes WHERE node_id = ?",
        (node_id,),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def get_nodes_by_ids(
    db: aiosqlite.Connection,
    node_ids: list[str] | tuple[str, ...] | set[str],
) -> dict[str, dict[str, Any]]:
    """Return ``{node_id: row}`` for the given ids in a single query.

    Replacement for ``for nid in ids: await get_node(...)`` loops which
    create one round-trip per id and dominate latency for endpoints that
    fetch a small bag of nodes (campaigns list, agent telemetry walks).
    Missing ids are simply omitted from the result map.
    """
    ids = list({nid for nid in node_ids if nid})
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    cursor = await db.execute(
        f"SELECT * FROM nodes WHERE node_id IN ({placeholders})",
        ids,
    )
    rows = await cursor.fetchall()
    return {row["node_id"]: dict(row) for row in rows}


async def update_node(
    db: aiosqlite.Connection,
    node_id: str,
    data: dict[str, Any] | None = None,
    *,
    expected_revision: int | None = None,
    **kw_fields: Any,
) -> dict[str, Any] | None:
    """Update arbitrary columns on a node.

    Accepts either a *data* dict **or** keyword arguments (or both -- they
    are merged).  Only keys present are written.  The ``insights`` field is
    automatically serialised to JSON if provided as a list.  ``updated_at``
    is always refreshed.

    When *expected_revision* is given, the UPDATE is guarded with
    ``AND revision = expected_revision`` so a read-check-then-write OCC path is
    actually ATOMIC (the bare update is last-write-wins under concurrency,
    especially since the prod connection runs autocommit). Returns ``None`` when
    no row matched — i.e. a concurrent writer already bumped the revision (or the
    node is gone) — which the caller should surface as a 409 conflict.
    """
    fields: dict[str, Any] = {**(data or {}), **kw_fields}

    if not fields:
        return await get_node(db, node_id)

    # Serialise list/dict fields to JSON strings.
    if "insights" in fields and isinstance(fields["insights"], list):
        fields["insights"] = json.dumps(fields["insights"])

    fields["updated_at"] = _now()

    set_clause = ", ".join(f"{k} = ?" for k in fields)

    if expected_revision is None:
        cursor = await db.execute(
            f"UPDATE nodes SET {set_clause} WHERE node_id = ?",
            list(fields.values()) + [node_id],
        )
    else:
        cursor = await db.execute(
            f"UPDATE nodes SET {set_clause} WHERE node_id = ? AND revision = ?",
            list(fields.values()) + [node_id, expected_revision],
        )
    await db.commit()
    if expected_revision is not None and cursor.rowcount == 0:
        return None
    return await get_node(db, node_id)


async def delete_node(
    db: aiosqlite.Connection,
    node_id: str,
) -> bool:
    """Delete a node by primary key.  Returns ``True`` if a row was removed."""
    cursor = await db.execute(
        "DELETE FROM nodes WHERE node_id = ?",
        (node_id,),
    )
    await db.commit()
    return cursor.rowcount > 0


# ------------------------------------------------------------------
# Listing with filters
# ------------------------------------------------------------------

async def list_nodes(
    db: aiosqlite.Connection,
    *,
    owner_user_id: str | None = None,
    node_type: str | None = None,
    lifecycle: str | None = None,
    outcome: str | None = None,
    repo_url: str | None = None,
    sharing_mode: str | None = None,
    root_only: bool = False,
    page: int = 1,
    per_page: int = 50,
) -> list[dict[str, Any]]:
    """Return a paginated list of nodes matching the supplied filters."""
    clauses: list[str] = []
    params: list[Any] = []

    if owner_user_id is not None:
        clauses.append("n.owner_user_id = ?")
        params.append(owner_user_id)
    if node_type is not None:
        clauses.append("n.node_type = ?")
        params.append(node_type)
    if lifecycle is not None:
        clauses.append("n.lifecycle = ?")
        params.append(lifecycle)
    if outcome is not None:
        clauses.append("n.outcome = ?")
        params.append(outcome)
    if repo_url is not None:
        clauses.append("n.repo_url = ?")
        params.append(repo_url)
    if sharing_mode is not None:
        clauses.append("n.sharing_mode = ?")
        params.append(sharing_mode)
    if root_only:
        clauses.append(
            "n.node_id NOT IN (SELECT child_id FROM node_edges)"
        )

    where = " AND ".join(clauses) if clauses else "1=1"
    offset = (page - 1) * per_page

    cursor = await db.execute(
        f"""
        SELECT n.* FROM nodes n
        WHERE {where}
        ORDER BY n.updated_at DESC
        LIMIT ? OFFSET ?
        """,
        params + [per_page, offset],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------
# Tree / ancestry helpers (recursive CTEs)
# ------------------------------------------------------------------

async def get_node_tree(
    db: aiosqlite.Connection,
    node_id: str,
    max_nodes: int | None = None,
) -> list[dict[str, Any]]:
    """Return the full descendant tree rooted at *node_id* (inclusive)."""
    limit = max_nodes if max_nodes is not None else 1_000_000_000
    cursor = await db.execute(
        """
        WITH RECURSIVE tree AS (
            SELECT node_id FROM nodes WHERE node_id = ?
            UNION
            SELECT e.child_id
            FROM node_edges e
            JOIN tree t ON e.parent_id = t.node_id
        )
        SELECT n.* FROM nodes n
        JOIN tree t ON n.node_id = t.node_id
        ORDER BY n.created_at ASC
        LIMIT ?
        """,
        (node_id, limit),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_node_tree_to_depth(
    db: aiosqlite.Connection,
    node_id: str,
    *,
    max_depth: int,
    max_nodes: int,
) -> list[dict[str, Any]]:
    """Return a root-anchored descendant tree through ``max_depth``.

    Walk one level at a time so ``max_nodes`` is a work bound, not merely an
    output limit applied after a recursive CTE has expanded the full graph.
    Parent ids are queried in batches to stay below database parameter limits;
    each level is de-duplicated and sorted before it becomes the next frontier.
    """
    if max_nodes <= 0:
        return []

    root = await get_node(db, node_id)
    if root is None:
        return []

    result = [root]
    if max_depth <= 0 or max_nodes == 1:
        return result

    # 500 leaves ample room under SQLite's traditional 999-variable limit
    # for the per-query LIMIT parameter while also working well on Postgres.
    batch_size = 500
    seen = {node_id}
    frontier = [node_id]

    for _depth in range(max_depth):
        remaining = max_nodes - len(result)
        if remaining <= 0 or not frontier:
            break

        level_by_id: dict[str, dict[str, Any]] = {}
        for offset in range(0, len(frontier), batch_size):
            parent_batch = frontier[offset : offset + batch_size]
            placeholders = ",".join("?" for _ in parent_batch)
            cursor = await db.execute(
                f"""
                SELECT n.*
                FROM nodes n
                WHERE n.node_id IN (
                    SELECT e.child_id
                    FROM node_edges e
                    WHERE e.parent_id IN ({placeholders})
                )
                ORDER BY n.created_at ASC, n.node_id ASC
                LIMIT ?
                """,
                [*parent_batch, max_nodes],
            )
            rows = await cursor.fetchall()
            for row in rows:
                node = dict(row)
                child_id = node["node_id"]
                if child_id not in seen:
                    level_by_id.setdefault(child_id, node)

        if not level_by_id:
            break

        ordered_level = sorted(
            level_by_id.values(),
            key=lambda node: (node.get("created_at") or "", node["node_id"]),
        )[:remaining]
        result.extend(ordered_level)
        frontier = [node["node_id"] for node in ordered_level]
        seen.update(frontier)

    return result


async def get_descendants(
    db: aiosqlite.Connection,
    root_id: str,
    owner_user_id: str | None = None,
    max_depth: int = 3,
    limit: int = 500,
    node_type: str | None = None,
) -> list[dict[str, Any]]:
    """Bounded descendant walk under *root_id* (exclusive of the root).

    Used by the semantic layer (runs:compare, /brief) where runs may be
    nested under experiment-plan nodes rather than sitting directly
    beneath the project. Depth- and row-bounded so a pathological DAG
    can't blow up the request. Plain ``WITH RECURSIVE`` works on both
    SQLite and Postgres; the GROUP BY collapses the per-depth rows the
    UNION keeps when a node is reachable along paths of different
    lengths.
    """
    type_clause = "WHERE n.node_type = ?" if node_type else ""
    params: list[Any] = [root_id, max_depth]
    if node_type:
        params.append(node_type)
    params.append(limit)
    cursor = await db.execute(
        f"""
        WITH RECURSIVE descendants(node_id, depth) AS (
            SELECT child_id, 1 FROM node_edges WHERE parent_id = ?
            UNION
            SELECT e.child_id, d.depth + 1
            FROM node_edges e
            JOIN descendants d ON e.parent_id = d.node_id
            WHERE d.depth < ?
        )
        SELECT n.* FROM nodes n
        JOIN (SELECT node_id FROM descendants GROUP BY node_id) d
          ON d.node_id = n.node_id
        {type_clause}
        ORDER BY n.created_at ASC
        LIMIT ?
        """,
        params,
    )
    try:
        rows = await cursor.fetchall()
    finally:
        await cursor.close()
    return [dict(r) for r in rows]


async def count_descendants(
    db: aiosqlite.Connection,
    root_id: str,
) -> int:
    """Count the root + all descendants (the full graph size for one root)."""
    cursor = await db.execute(
        """
        WITH RECURSIVE tree AS (
            SELECT node_id FROM nodes WHERE node_id = ?
            UNION
            SELECT e.child_id
            FROM node_edges e
            JOIN tree t ON e.parent_id = t.node_id
        )
        SELECT COUNT(*) FROM tree
        """,
        (root_id,),
    )
    row = await cursor.fetchone()
    return int(row[0]) if row else 0


async def count_descendants_batch(
    db: aiosqlite.Connection,
    root_ids: list[str],
) -> dict[str, int]:
    """Descendant counts (root + all descendants) for MANY roots in ONE recursive
    CTE. Replaces a per-root N+1 (one recursive CTE per card) on the Explore feed,
    which got proportionally slower with page size and corpus growth.
    """
    ids = [r for r in dict.fromkeys(root_ids) if r]
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    cursor = await db.execute(
        f"""
        WITH RECURSIVE tree(root_id, node_id) AS (
            SELECT node_id, node_id FROM nodes WHERE node_id IN ({placeholders})
            UNION
            SELECT t.root_id, e.child_id
            FROM node_edges e
            JOIN tree t ON e.parent_id = t.node_id
        )
        SELECT root_id, COUNT(*) AS n FROM tree GROUP BY root_id
        """,
        tuple(ids),
    )
    rows = await cursor.fetchall()
    counts: dict[str, int] = {rid: 0 for rid in ids}
    for row in rows:
        d = dict(row) if hasattr(row, "keys") else {"root_id": row[0], "n": row[1]}
        counts[d["root_id"]] = int(d["n"])
    return counts


async def get_connected_component(
    db: aiosqlite.Connection,
    node_id: str,
    max_nodes: int | None = None,
) -> list[dict[str, Any]]:
    """Return nodes connected to *node_id* by parent/child edges.

    Dashboard and agent canvases need the whole visible graph component, not
    an N+1 Python BFS. The recursive CTE walks both edge directions and lets
    the database compute the closure in one query.

    NOTE: A recursive CTE must have exactly one non-recursive (anchor) arm
    and one recursive arm joined by ``UNION``. The previous implementation
    expressed the "walk both directions" rule as three UNION arms, which
    PostgreSQL parses as an anchor that *itself* references the CTE - it
    rejects the query with::

        InvalidRecursionError: recursive reference to query "connected"
        must not appear within its non-recursive term

    The fix is to inline the bidirectional edge step as a single derived
    table inside one recursive arm. Identical results in SQLite + Postgres.
    """
    limit = max_nodes if max_nodes is not None else 1_000_000_000
    cursor = await db.execute(
        """
        WITH RECURSIVE connected AS (
            SELECT node_id FROM nodes WHERE node_id = ?
            UNION
            SELECT step.next_id FROM (
                SELECT e.child_id  AS next_id, e.parent_id AS prev_id FROM node_edges e
                UNION ALL
                SELECT e.parent_id AS next_id, e.child_id  AS prev_id FROM node_edges e
            ) step
            JOIN connected c ON step.prev_id = c.node_id
        )
        SELECT n.* FROM nodes n
        JOIN connected c ON n.node_id = c.node_id
        ORDER BY n.created_at ASC
        LIMIT ?
        """,
        (node_id, limit),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_node_ancestry(
    db: aiosqlite.Connection,
    node_id: str,
) -> list[dict[str, Any]]:
    """Return all ancestors of *node_id* (inclusive), walking edges upward."""
    cursor = await db.execute(
        """
        WITH RECURSIVE ancestors AS (
            SELECT node_id FROM nodes WHERE node_id = ?
            UNION
            SELECT e.parent_id
            FROM node_edges e
            JOIN ancestors a ON e.child_id = a.node_id
        )
        SELECT n.* FROM nodes n
        JOIN ancestors a ON n.node_id = a.node_id
        """,
        (node_id,),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def find_root_node_id(
    db: aiosqlite.Connection,
    node_id: str,
) -> str | None:
    """Walk up the DAG from *node_id* and return the topmost ancestor.

    If the node has no parents it is its own root.  When multiple paths
    exist the function returns the first root encountered (depth-first).
    """
    cursor = await db.execute(
        """
        WITH RECURSIVE ancestors AS (
            SELECT node_id, node_id AS current_id FROM nodes WHERE node_id = ?
            UNION
            SELECT a.node_id, e.parent_id
            FROM node_edges e
            JOIN ancestors a ON e.child_id = a.current_id
        )
        SELECT current_id FROM ancestors
        WHERE current_id NOT IN (SELECT child_id FROM node_edges)
        LIMIT 1
        """,
        (node_id,),
    )
    row = await cursor.fetchone()
    return str(row[0]) if row else None


async def find_root_node_ids(
    db: aiosqlite.Connection,
    node_id: str,
) -> list[str]:
    """Walk up the DAG from *node_id* and return every topmost ancestor.

    Atlas intentionally allows a DAG: normal operations like decisions,
    experiment plans, and merges can create multiple parent paths. For graph-
    scoped access, visibility/collaboration is inherited from any root graph
    containing the node. If ``node_id`` itself is a root, it is returned.
    Missing nodes return an empty list.
    """
    cursor = await db.execute(
        """
        WITH RECURSIVE ancestors AS (
            SELECT node_id, node_id AS current_id FROM nodes WHERE node_id = ?
            UNION
            SELECT a.node_id, e.parent_id
            FROM node_edges e
            JOIN ancestors a ON e.child_id = a.current_id
        )
        SELECT DISTINCT current_id FROM ancestors
        WHERE current_id NOT IN (SELECT child_id FROM node_edges)
        ORDER BY current_id
        """,
        (node_id,),
    )
    rows = await cursor.fetchall()
    return [str(row[0]) for row in rows]


# ------------------------------------------------------------------
# Revision management
# ------------------------------------------------------------------

async def increment_revision(
    db: aiosqlite.Connection,
    node_id: str,
    expected_revision: int,
) -> int | None:
    """Atomically increment the revision if it matches *expected_revision*.

    Returns the new revision on success, or ``None`` on conflict.
    """
    now = _now()
    new_rev = expected_revision + 1
    cursor = await db.execute(
        """
        UPDATE nodes
        SET revision = ?, updated_at = ?
        WHERE node_id = ? AND revision = ?
        """,
        (new_rev, now, node_id, expected_revision),
    )
    await db.commit()
    if cursor.rowcount == 0:
        return None
    return new_rev
