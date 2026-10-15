"""
Tag management service -- create, update, delete tags and manage tag assignments.

Tags are scoped to a root node.  Each operation that modifies tags also bumps
the relevant node/root revision.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from atlas_graph.auth.access_check import require_node_access
from atlas_graph.db.repos import node_repo
from atlas_graph.services.node_service import _full_node_response


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _make_tag_id() -> str:
    """Generate a tag ID in the form ``tag-{12-char-hex}``."""
    return f"tag-{uuid.uuid4().hex[:12]}"


async def _begin_mutation(db) -> tuple[str, Any]:
    """Open a real transaction on both production Postgres and local SQLite."""
    raw = getattr(db, "raw", None)
    if raw is not None:
        transaction = raw.transaction()
        await transaction.start()
        return "postgres", transaction
    if getattr(db, "in_transaction", False):
        savepoint = f"tag_mutation_{uuid.uuid4().hex[:10]}"
        await db.execute(f"SAVEPOINT {savepoint}")
        return "savepoint", savepoint
    await db.execute("BEGIN IMMEDIATE")
    return "sqlite", None


async def _commit_mutation(db, transaction: tuple[str, Any]) -> None:
    kind, token = transaction
    if kind == "postgres":
        await token.commit()
    elif kind == "savepoint":
        await db.execute(f"RELEASE SAVEPOINT {token}")
    else:
        await db.commit()


async def _rollback_mutation(db, transaction: tuple[str, Any]) -> None:
    kind, token = transaction
    try:
        if kind == "postgres":
            await token.rollback()
        elif kind == "savepoint":
            await db.execute(f"ROLLBACK TO SAVEPOINT {token}")
            await db.execute(f"RELEASE SAVEPOINT {token}")
        else:
            await db.rollback()
    except Exception:
        pass


async def _claim_revision(
    db,
    node_id: str,
    expected_revision: int,
    now: str,
) -> int:
    """Atomically reserve the next node revision inside the tag transaction."""
    new_revision = int(expected_revision) + 1
    cursor = await db.execute(
        """
        UPDATE nodes
        SET revision = ?, updated_at = ?
        WHERE node_id = ? AND revision = ?
        """,
        (new_revision, now, node_id, int(expected_revision)),
    )
    if cursor.rowcount == 0:
        current = await node_repo.get_node(db, node_id)
        current_revision = current["revision"] if current is not None else "missing"
        raise ValueError(
            f"409 conflict: expected revision {expected_revision}, "
            f"current is {current_revision}"
        )
    return new_revision


# ---------------------------------------------------------------------------
# create_tag
# ---------------------------------------------------------------------------

async def create_tag(db, user_id: str, req) -> dict:
    """
    Create a new tag scoped to the given root node.

    Returns a dict with ``tag`` and ``node`` (the updated root node).
    """
    await require_node_access(db, user_id, req.root_node_id, "write")
    now = _now()
    tag_id = _make_tag_id()

    # Store colors in one canonical hex representation.
    bg_color = req.bg_color.upper() if req.bg_color else req.bg_color
    text_color = req.text_color.upper() if req.text_color else req.text_color

    transaction = await _begin_mutation(db)
    try:
        await _claim_revision(
            db,
            req.root_node_id,
            req.expected_revision,
            now,
        )
        await db.execute(
            """INSERT INTO tags (tag_id, root_node_id, name, bg_color, text_color,
               one_only, track_history, history_next_index, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
            (
                tag_id, req.root_node_id, req.name, bg_color, text_color,
                req.one_only, req.track_history, now, now,
            ),
        )
        await _commit_mutation(db, transaction)
    except Exception:
        await _rollback_mutation(db, transaction)
        raise

    tag_resp = {
        "tag_id": tag_id,
        "name": req.name,
        "bg_color": bg_color,
        "text_color": text_color,
        "one_only": req.one_only,
        "track_history": req.track_history,
        "history_next_index": 0,
    }
    node_resp = await _full_node_response(db, req.root_node_id, user_id=user_id)

    return {"tag": tag_resp, "node": node_resp}


# ---------------------------------------------------------------------------
# update_tag
# ---------------------------------------------------------------------------

async def update_tag(db, user_id: str, req) -> dict:
    """
    Update an existing tag.

    Returns a dict with ``tag`` and ``node`` (the updated root node).
    """
    await require_node_access(db, user_id, req.root_node_id, "write")
    now = _now()
    updates: dict[str, Any] = {"updated_at": now}

    if req.name is not None:
        updates["name"] = req.name
    if req.bg_color is not None:
        updates["bg_color"] = req.bg_color.upper()
    if req.text_color is not None:
        updates["text_color"] = req.text_color.upper()
    if req.one_only is not None:
        updates["one_only"] = req.one_only
    if req.track_history is not None:
        updates["track_history"] = req.track_history

    transaction = await _begin_mutation(db)
    try:
        await _claim_revision(
            db,
            req.root_node_id,
            req.expected_revision,
            now,
        )
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        vals = list(updates.values()) + [req.tag_id, req.root_node_id]
        cursor = await db.execute(
            f"UPDATE tags SET {set_clause} "
            "WHERE tag_id = ? AND root_node_id = ?",
            vals,
        )
        if cursor.rowcount == 0:
            raise ValueError(
                f"Tag {req.tag_id} not found for root {req.root_node_id}"
            )
        await _commit_mutation(db, transaction)
    except Exception:
        await _rollback_mutation(db, transaction)
        raise

    # Re-fetch tag for response
    cursor = await db.execute("SELECT * FROM tags WHERE tag_id = ?", (req.tag_id,))
    columns = [desc[0] for desc in cursor.description]
    raw = await cursor.fetchone()
    tag_row = dict(zip(columns, raw))

    tag_resp = {
        "tag_id": tag_row["tag_id"],
        "name": tag_row["name"],
        "bg_color": tag_row["bg_color"],
        "text_color": tag_row["text_color"],
        "one_only": bool(tag_row["one_only"]),
        "track_history": bool(tag_row["track_history"]),
        "history_next_index": tag_row["history_next_index"],
    }
    node_resp = await _full_node_response(db, req.root_node_id, user_id=user_id)

    return {"tag": tag_resp, "node": node_resp}


# ---------------------------------------------------------------------------
# delete_tag
# ---------------------------------------------------------------------------

async def delete_tag(db, user_id: str, req) -> None:
    """Delete a tag and increment root node revision."""
    await require_node_access(db, user_id, req.root_node_id, "write")
    now = _now()
    transaction = await _begin_mutation(db)
    try:
        await _claim_revision(
            db,
            req.root_node_id,
            req.expected_revision,
            now,
        )
        cursor = await db.execute(
            "DELETE FROM tags WHERE tag_id = ? AND root_node_id = ?",
            (req.tag_id, req.root_node_id),
        )
        if cursor.rowcount == 0:
            raise ValueError(
                f"Tag {req.tag_id} not found for root {req.root_node_id}"
            )
        await _commit_mutation(db, transaction)
    except Exception:
        await _rollback_mutation(db, transaction)
        raise


# ---------------------------------------------------------------------------
# set_tag_assignments
# ---------------------------------------------------------------------------

async def set_tag_assignments(db, user_id: str, req) -> dict:
    """
    Set the tag assignments for a node (replaces existing assignments).

    Handles one_only: if a one_only tag is assigned here, remove it from any
    other node.

    If track_history: record in tag_history with superseded_at,
    superseded_by_node_id.

    Increments node revision.
    """
    await require_node_access(db, user_id, req.node_id, "write")
    now = _now()
    transaction = await _begin_mutation(db)
    try:
        await _claim_revision(db, req.node_id, req.expected_revision, now)

        cursor = await db.execute(
            "SELECT tag_id FROM tag_assignments WHERE node_id = ?",
            (req.node_id,),
        )
        current_tag_ids = {r[0] for r in await cursor.fetchall()}
        desired_tag_ids = set(req.tag_ids)
        to_add = desired_tag_ids - current_tag_ids
        to_remove = current_tag_ids - desired_tag_ids

        for tid in sorted(to_remove):
            await db.execute(
                "DELETE FROM tag_assignments WHERE tag_id = ? AND node_id = ?",
                (tid, req.node_id),
            )

        root_ids = set(await node_repo.find_root_node_ids(db, req.node_id))
        for tid in sorted(to_add):
            # A no-op UPDATE locks this tag row in Postgres. Together with
            # deterministic tag ordering it serializes concurrent one_only
            # moves without introducing cross-tag deadlocks.
            lock_cursor = await db.execute(
                "UPDATE tags SET updated_at = updated_at WHERE tag_id = ?",
                (tid,),
            )
            if lock_cursor.rowcount == 0:
                raise ValueError(f"Tag {tid} not found")

            cursor = await db.execute("SELECT * FROM tags WHERE tag_id = ?", (tid,))
            columns = [desc[0] for desc in cursor.description]
            raw = await cursor.fetchone()
            if raw is None:
                raise ValueError(f"Tag {tid} not found")
            tag_row = dict(zip(columns, raw))
            if tag_row["root_node_id"] not in root_ids:
                raise ValueError(
                    f"Tag {tid} is not scoped to a root of node {req.node_id}"
                )

            is_one_only = bool(tag_row["one_only"])
            is_track_history = bool(tag_row["track_history"])
            if is_one_only:
                cursor = await db.execute(
                    "SELECT node_id FROM tag_assignments "
                    "WHERE tag_id = ? AND node_id != ? ORDER BY node_id",
                    (tid, req.node_id),
                )
                other_nodes = [r[0] for r in await cursor.fetchall()]
                history_index = int(tag_row["history_next_index"])

                for other_nid in other_nodes:
                    await db.execute(
                        "DELETE FROM tag_assignments WHERE tag_id = ? AND node_id = ?",
                        (tid, other_nid),
                    )
                    # The assignment mutation must invalidate stale views of
                    # the node it was removed from too.
                    await db.execute(
                        "UPDATE nodes SET revision = revision + 1, updated_at = ? "
                        "WHERE node_id = ?",
                        (now, other_nid),
                    )
                    if is_track_history:
                        await db.execute(
                            """INSERT INTO tag_history
                               (tag_id, node_id, history_index, superseded_at,
                                superseded_by_node_id)
                               VALUES (?, ?, ?, ?, ?)""",
                            (tid, other_nid, history_index, now, req.node_id),
                        )
                        history_index += 1

                if is_track_history and history_index != int(
                    tag_row["history_next_index"]
                ):
                    await db.execute(
                        "UPDATE tags SET history_next_index = ? WHERE tag_id = ?",
                        (history_index, tid),
                    )

            await db.execute(
                "INSERT INTO tag_assignments (tag_id, node_id, created_at) "
                "VALUES (?, ?, ?)",
                (tid, req.node_id, now),
            )

        await _commit_mutation(db, transaction)
    except Exception:
        await _rollback_mutation(db, transaction)
        raise

    return await _full_node_response(db, req.node_id, user_id=user_id)
