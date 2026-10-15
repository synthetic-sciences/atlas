"""Repository functions for the ``node_access_rules`` table."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import aiosqlite


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


async def set_access_rule(
    db: aiosqlite.Connection,
    *,
    node_id: str,
    user_id: str,
    access_level: str,
) -> dict[str, Any]:
    """Insert or replace an access rule for (node_id, user_id).

    If a rule already exists for the pair it is updated to the new level;
    otherwise a new row is created.
    """
    now = _now()

    # Check for existing rule.
    cursor = await db.execute(
        """
        SELECT id FROM node_access_rules
        WHERE node_id = ? AND user_id = ?
        """,
        (node_id, user_id),
    )
    existing = await cursor.fetchone()

    if existing:
        await db.execute(
            """
            UPDATE node_access_rules SET access_level = ?
            WHERE node_id = ? AND user_id = ?
            """,
            (access_level, node_id, user_id),
        )
    else:
        await db.execute(
            """
            INSERT INTO node_access_rules (node_id, user_id, access_level, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (node_id, user_id, access_level, now),
        )

    await db.commit()
    return {
        "node_id": node_id,
        "user_id": user_id,
        "access_level": access_level,
        "created_at": now,
    }


async def get_access_rules(
    db: aiosqlite.Connection,
    node_id: str,
) -> list[dict[str, Any]]:
    """Return all access rules for a given node."""
    cursor = await db.execute(
        "SELECT * FROM node_access_rules WHERE node_id = ? ORDER BY created_at ASC",
        (node_id,),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_effective_permissions(
    db: aiosqlite.Connection,
    node_id: str,
    user_id: str,
) -> dict[str, bool]:
    """Compute effective boolean permissions for a user on a node.

    Access levels are cumulative:
    * USER        -> can_view
    * USER_WRITE  -> can_view + can_write
    * USER_ADMIN  -> can_view + can_write + can_admin

    Collaboration-on-downgrade behaviour: if the *owner* of this node
    is on a plan without ``collaboration_enabled`` (e.g. they've
    downgraded to Free), every non-owner is clamped to view-only here.
    The access rule rows are preserved so re-upgrading restores write
    immediately. Owner permissions never change.
    """
    cursor = await db.execute(
        """
        SELECT access_level FROM node_access_rules
        WHERE node_id = ? AND user_id = ?
        """,
        (node_id, user_id),
    )
    row = await cursor.fetchone()

    perms = {"can_view": False, "can_write": False, "can_admin": False}
    if row is None:
        return perms

    level = row["access_level"]
    if level in ("USER", "USER_WRITE", "USER_ADMIN"):
        perms["can_view"] = True
    if level in ("USER_WRITE", "USER_ADMIN"):
        perms["can_write"] = True
    if level == "USER_ADMIN":
        perms["can_admin"] = True

    if not perms["can_write"] and not perms["can_admin"]:
        return perms

    # Plan-aware freeze. Cheap (single fetch + cached plan lookup) but
    # imported lazily to avoid a config-import cycle in tests.
    cursor = await db.execute(
        "SELECT owner_user_id FROM nodes WHERE node_id = ?",
        (node_id,),
    )
    owner_row = await cursor.fetchone()
    if not owner_row:
        return perms
    owner_user_id = owner_row[0] if not hasattr(owner_row, "keys") else owner_row["owner_user_id"]
    if owner_user_id == user_id:
        return perms  # owner is never frozen by their own plan

    try:
        from atlas_graph import config
        from atlas_graph.runtime import collaboration_allowed
        if not await collaboration_allowed(db, owner_user_id):
            perms["can_write"] = False
            perms["can_admin"] = False
    except Exception:
        # Match auth.access_check: fail closed on plan lookup errors so a
        # downgraded/offline billing state cannot accidentally leave write/admin
        # enabled for collaborators.
        perms["can_write"] = False
        perms["can_admin"] = False

    return perms


async def remove_access_rule(
    db: aiosqlite.Connection,
    node_id: str,
    user_id: str,
) -> bool:
    """Remove an access rule. Returns ``True`` if a row was deleted."""
    cursor = await db.execute(
        "DELETE FROM node_access_rules WHERE node_id = ? AND user_id = ?",
        (node_id, user_id),
    )
    await db.commit()
    return cursor.rowcount > 0
