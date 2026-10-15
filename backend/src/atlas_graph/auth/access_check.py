"""
Node access control.

Checks whether a user can view, write, or admin a node based on:
1. Ownership (owner can do everything)
2. Sharing mode (public = anyone can view, unlisted = anyone with link)
3. Collaborator role (viewer, editor, admin)
"""

from __future__ import annotations

import logging

_log = logging.getLogger(__name__)


async def _owner_can_share_writes(db, owner_user_id: str) -> bool:
    """True when the node owner is on a plan that includes collaboration.

    Used to freeze collaborator write/admin access when an owner has
    downgraded off the collaboration plan. Fails **closed** on lookup
    error: if we can't confirm the plan covers collaboration, we don't
    grant write — better to bounce a collaborator with a 403 they can
    retry than to silently let them write while plan state is unknown.
    The exception is logged so a spike in fail-closes is visible.
    """
    try:
        from atlas_graph import config
        from atlas_graph.runtime import collaboration_allowed
        return await collaboration_allowed(db, owner_user_id)
    except Exception as exc:
        _log.warning(
            "owner_can_share_writes lookup failed for owner=%s: %s — "
            "denying collaborator write (fail-closed)",
            owner_user_id,
            exc,
        )
        return False


async def check_node_access(
    db, user_id: str, node_id: str, require: str = "view"
) -> bool | None:
    """Check if user has the required access level to a node.

    Access is graph-scoped: visibility/collaboration lives on project roots
    (nodes with no parents), and every descendant inherits it. A DAG node may be
    reachable from multiple roots; access through any root is sufficient. For
    backwards compatibility with pre-graph-scoped data, a direct per-node owner
    or access rule still grants access.

    Parameters
    ----------
    db : aiosqlite.Connection
    user_id : str
        The authenticated user requesting access.
    node_id : str
        The node to check access for.
    require : str
        Access level needed: ``"view"`` | ``"write"`` | ``"admin"``.

    Returns
    -------
    bool | None
        True if access is granted, False if denied, None if node not found.
    """
    cursor = await db.execute(
        "SELECT owner_user_id, sharing_mode FROM nodes WHERE node_id = ?",
        (node_id,),
    )
    row = await cursor.fetchone()
    if not row:
        return None  # Node does not exist

    owner_id = row[0]

    # Anonymous callers (public Explore, fork preview, repo browser) own
    # nothing and hold no collaborator rules. Skip every user-scoped lookup for
    # them: besides being pointless, ``node_access_rules.user_id`` is a UUID on
    # Postgres, so querying it with the ``"__anonymous__"`` sentinel raises a
    # DataError. They reach access only through public/unlisted visibility below.
    is_anon = not user_id or user_id == "__anonymous__"

    # Legacy compatibility: before graph-scoped access, node ownership and
    # direct rules were meaningful per-node. Keep honoring them so existing
    # data and orphan nodes don't become inaccessible.
    if not is_anon and owner_id == user_id:
        return True

    from atlas_graph.db.repos import node_repo

    root_ids = await node_repo.find_root_node_ids(db, node_id)
    if not root_ids:
        return None
    candidate_ids = list(dict.fromkeys([*root_ids, node_id]))
    placeholders = ",".join("?" for _ in candidate_ids)

    root_cursor = await db.execute(
        f"SELECT node_id, owner_user_id, sharing_mode FROM nodes WHERE node_id IN ({placeholders})",
        tuple(candidate_ids),
    )
    root_rows = await root_cursor.fetchall()
    by_id = {r[0]: {"owner_user_id": r[1], "sharing_mode": r[2] or "private"} for r in root_rows}

    # Owner of any containing graph has full access to every node in it.
    if not is_anon:
        for rid in root_ids:
            if by_id.get(rid, {}).get("owner_user_id") == user_id:
                return True

    # Check collaborator access rules on any containing root, with direct
    # per-node access rules as a legacy fallback. Anonymous callers have none.
    access_rows = []
    if not is_anon:
        cursor = await db.execute(
            f"""
            SELECT node_id, access_level FROM node_access_rules
            WHERE node_id IN ({placeholders}) AND user_id = ?
            """,
            tuple(candidate_ids) + (user_id,),
        )
        access_rows = await cursor.fetchall()
    for access_row in access_rows:
        rule_node_id = access_row[0]
        level = access_row[1]
        if require == "view":
            return True  # Any access rule grants view
        # Plan-aware freeze: when the owner downgrades off the
        # collaboration plan, every non-owner is clamped to view-only
        # without removing the access rule rows. Re-upgrading restores
        # write immediately. Owner permissions are checked above and
        # are never affected.
        rule_owner = by_id.get(rule_node_id, {}).get("owner_user_id") or owner_id
        if not await _owner_can_share_writes(db, rule_owner):
            continue
        if require == "write":
            if level in ("USER_WRITE", "USER_ADMIN"):
                return True
        elif require == "admin":
            if level == "USER_ADMIN":
                return True

    if require == "view":
        from atlas_graph import config
        public_reads_enabled = bool(config.PUBLIC_GRAPHS_ENABLED)
        for rid in root_ids:
            sharing_mode = by_id.get(rid, {}).get("sharing_mode", "private")
            # Public roots: anyone can view the whole graph. Unlisted roots:
            # anyone who has the link/node id can view the whole graph.
            if public_reads_enabled and sharing_mode in ("public", "unlisted"):
                return True

    # Legacy public/unlisted per-node fallback for old individually shared
    # nodes whose root has not been updated yet.
    if (
        require == "view"
        and public_reads_enabled
        and (row[1] or "private") in ("public", "unlisted")
    ):
        return True

    return False


async def require_node_access(
    db, user_id: str, node_id: str, require: str = "view"
) -> None:
    """Like :func:`check_node_access` but raises ``ValueError`` if denied.

    Raises ``ValueError("Node ... not found")`` if the node does not exist,
    or ``ValueError("Access denied: ...")`` if the user lacks the required
    access level.
    """
    result = await check_node_access(db, user_id, node_id, require)
    if result is None:
        raise ValueError(f"Node {node_id} not found")
    if result is False:
        raise ValueError(
            f"Access denied: requires {require} access to node {node_id}"
        )
