"""
Sharing service -- manage visibility, sharing mode, and collaborator access
for nodes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from atlas_graph import config
from atlas_graph.auth.access_check import require_node_access
from atlas_graph.db.repos import node_repo
from atlas_graph.models.common import (
    AccessLevel,
    CollaboratorRole,
    ROLE_TO_ACCESS,
    ACCESS_TO_ROLE,
    SharingMode,
)


class CollaborationGatedError(Exception):
    """Raised when a Free-plan user tries to collaborate on a private project.

    Publishing a graph publicly/unlisted is free for everyone (the public
    archive stays open). What's gated is granting named collaborators
    (editors/admins) on a NON-public graph — a paid team feature. Mapped to
    HTTP 402 by the sharing + Atlas CLI core route error handlers. Owner
    permissions are unaffected and existing shares are not retroactively
    revoked; this only blocks creating new private collaboration. Existing
    collaborators remain visible (clamped to read-only) when the owner is on
    Free.
    """

    def __init__(self, plan_label: str, action: str):
        super().__init__(
            "Private collaboration is not currently available for this account."
        )
        self.plan_label = plan_label
        self.action = action


class PublicSharingDisabledError(ValueError):
    """Public/unlisted graph publication is not launched on this server."""


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


async def _collaboration_enabled_for(db, user_id: str) -> bool:
    """Look up ``user_id``'s plan and return whether collaboration is
    included. Defaults to False for unknown users / DB hiccups so the
    gate fails closed.
    """
    try:
        from atlas_graph.runtime import collaboration_allowed
        return await collaboration_allowed(db, user_id)
    except Exception:
        return False


_ACCESS_RANK = {
    AccessLevel.USER.value: 0,
    AccessLevel.USER_WRITE.value: 1,
    AccessLevel.USER_ADMIN.value: 2,
}


async def _collaborator_update_expands_access(
    db,
    *,
    root_id: str,
    owner_user_id: str,
    collaborators: list[Any],
) -> bool:
    """Return whether a replacement collaborator list grants more access.

    Owners must always be able to revoke or reduce access after a legacy
    collaboration entitlement ends. New collaborators and role elevations stay
    gated. Unknown requested accounts count as additions so the check fails
    closed without changing the existing sync behavior for entitled owners.
    """
    cursor = await db.execute(
        "SELECT user_id, access_level FROM node_access_rules WHERE node_id = ?",
        (root_id,),
    )
    current = {row[0]: str(row[1]) for row in await cursor.fetchall()}

    for collaborator in collaborators:
        cursor = await db.execute(
            "SELECT user_id FROM users WHERE email = ?", (collaborator.email,)
        )
        user_row = await cursor.fetchone()
        if user_row is None:
            return True
        collaborator_user_id = user_row[0]
        if collaborator_user_id == owner_user_id:
            continue

        requested_level = ROLE_TO_ACCESS.get(
            collaborator.role, AccessLevel.USER
        ).value
        current_level = current.get(collaborator_user_id)
        if current_level is None:
            return True
        if _ACCESS_RANK.get(requested_level, 0) > _ACCESS_RANK.get(
            current_level, -1
        ):
            return True

    return False


def _derive_visibility(sharing_mode: str, collaborator_count: int) -> str:
    """
    Derive the effective visibility from sharing_mode and collaborator presence.

    - private + no collaborators => private
    - private + collaborators    => shared
    - unlisted                    => unlisted
    - public                      => public
    """
    if sharing_mode == "public":
        return "public"
    if sharing_mode == "unlisted":
        return "unlisted"
    # private
    return "shared" if collaborator_count > 0 else "private"


async def _build_sharing_response(
    db, node_row: dict, user_id: str, requested_node_id: str | None = None
) -> dict:
    """Build a SharingResponse-compatible dict from a node row."""
    node_id = node_row["node_id"]
    owner_user_id = node_row["owner_user_id"]
    sharing_mode = node_row.get("sharing_mode", "private")
    collaboration_enabled = await _collaboration_enabled_for(db, owner_user_id)

    # Get owner email
    cursor = await db.execute(
        "SELECT email FROM users WHERE user_id = ?", (owner_user_id,)
    )
    owner_row = await cursor.fetchone()
    owner_email = owner_row[0] if owner_row else ""

    # Get collaborators from node_access_rules
    cursor = await db.execute(
        """SELECT nar.user_id, nar.access_level, u.email
           FROM node_access_rules nar
           JOIN users u ON u.user_id = nar.user_id
           WHERE nar.node_id = ?""",
        (node_id,),
    )
    collab_rows = await cursor.fetchall()

    collaborators = []
    for crow in collab_rows:
        c_user_id, access_level, email = crow
        role_enum = ACCESS_TO_ROLE.get(
            AccessLevel(access_level), CollaboratorRole.viewer
        )
        collaborators.append({
            "email": email,
            "role": role_enum.value,
        })

    collab_count = len(collaborators)
    visibility = _derive_visibility(sharing_mode, collab_count)

    # Effective permissions for requesting user
    is_owner = owner_user_id == user_id
    can_view = True  # if we got here, the user has some access
    can_write = is_owner
    can_admin = is_owner

    if not is_owner:
        cursor = await db.execute(
            "SELECT access_level FROM node_access_rules WHERE node_id = ? AND user_id = ?",
            (node_id, user_id),
        )
        access_row = await cursor.fetchone()
        if access_row:
            level = access_row[0]
            # Keep this response aligned with check_node_access: legacy rows
            # continue to grant view, but write/admin freeze when the graph
            # owner's collaboration entitlement ends.
            can_write = collaboration_enabled and level in (
                "USER_WRITE",
                "USER_ADMIN",
            )
            can_admin = collaboration_enabled and level == "USER_ADMIN"
        else:
            can_write = False
            can_admin = False

    return {
        "node_id": node_id,
        "project_id": node_id,
        "requested_node_id": requested_node_id or node_id,
        "owner_user_id": owner_user_id,
        "owner_email": owner_email,
        "is_owner": is_owner,
        # The server-side owner entitlement is the authority for collaborator
        # mutations and write access. Returning that same decision keeps the UI
        # fail-closed without reconstructing it from retired billing catalogs.
        "collaboration_enabled": collaboration_enabled,
        "sharing_mode": sharing_mode,
        "visibility": visibility,
        "effective": {
            "can_view": can_view,
            "can_write": can_write,
            "can_admin": can_admin,
        },
        "collaborators": collaborators,
        "updated_at": node_row.get("updated_at", ""),
    }


# ---------------------------------------------------------------------------
# get_sharing
# ---------------------------------------------------------------------------

async def get_sharing(db, user_id: str, node_id: str) -> dict:
    """Retrieve sharing information for the graph containing a node."""
    await require_node_access(db, user_id, node_id, "view")

    root_id = await node_repo.find_root_node_id(db, node_id) or node_id
    row = await node_repo.get_node(db, root_id)
    if row is None:
        raise ValueError(f"Node {node_id} not found")
    return await _build_sharing_response(db, row, user_id, requested_node_id=node_id)


async def get_sharing_summaries(db, user_id: str, node_ids: list[str]) -> dict:
    """Batch-read compact sharing summaries for multiple nodes.

    The CLI command is read-only and should not fail the whole batch
    because one node is missing or inaccessible. Each item returns either a
    compact summary or an error marker keyed by node_id.
    """
    summaries: list[dict[str, Any]] = []
    for node_id in node_ids:
        try:
            await require_node_access(db, user_id, node_id, "view")
            root_id = await node_repo.find_root_node_id(db, node_id) or node_id
            row = await node_repo.get_node(db, root_id)
            if row is None:
                summaries.append({
                    "node_id": node_id,
                    "ok": False,
                    "error": "not_found",
                })
                continue
            sharing = await _build_sharing_response(db, row, user_id, requested_node_id=node_id)
            summaries.append({
                "node_id": node_id,
                "project_id": sharing["project_id"],
                "ok": True,
                "sharing_mode": sharing["sharing_mode"],
                "visibility": sharing["visibility"],
                "owner_user_id": sharing["owner_user_id"],
                "is_owner": sharing["is_owner"],
                "can_view": sharing["effective"]["can_view"],
                "can_write": sharing["effective"]["can_write"],
                "can_admin": sharing["effective"]["can_admin"],
                "collaborator_count": len(sharing.get("collaborators") or []),
                "updated_at": sharing.get("updated_at", ""),
            })
        except Exception as exc:
            summaries.append({
                "node_id": node_id,
                "ok": False,
                "error": str(exc),
            })
    return {"summaries": summaries}


# ---------------------------------------------------------------------------
# set_sharing
# ---------------------------------------------------------------------------

async def set_sharing(db, user_id: str, node_id: str, req) -> dict:
    """
    Update sharing for the graph containing a node.

    Atlas visibility is graph-scoped: the project root's sharing_mode and
    collaborator rules define access for every descendant. A caller may pass any
    node in the graph; the mutation resolves to the root.
    """
    await require_node_access(db, user_id, node_id, "admin")

    root_id = await node_repo.find_root_node_id(db, node_id) or node_id
    row = await node_repo.get_node(db, root_id)
    if row is None:
        raise ValueError(f"Node {node_id} not found")

    # Plan gate: collaboration on a NON-public project (named editors/admins on
    # a private or unlisted graph) is a paid feature. Publishing a graph
    # publicly/unlisted, and locking it back to private, are always free — the
    # public archive stays open to everyone, monetization sits on private teams.
    current_mode = row.get("sharing_mode", "private")
    target_mode = req.sharing_mode.value if req.sharing_mode is not None else current_mode
    if target_mode in ("public", "unlisted") and not config.PUBLIC_GRAPHS_ENABLED:
        raise PublicSharingDisabledError("Public graph sharing is currently unavailable")
    owner_user_id = row["owner_user_id"]
    expands_private_collab = bool(
        req.collaborators
        and target_mode != "public"
        and await _collaborator_update_expands_access(
            db,
            root_id=root_id,
            owner_user_id=owner_user_id,
            collaborators=req.collaborators,
        )
    )
    if expands_private_collab:
        if not await _collaboration_enabled_for(db, owner_user_id):
            from atlas_graph.runtime import collaboration_allowed
            from atlas_graph.runtime import collaboration_label
            plan_label = await collaboration_label(db, owner_user_id)
            raise CollaborationGatedError(plan_label, "collaborate on a private project")

    now = _now()

    # Update sharing_mode if provided
    if req.sharing_mode is not None:
        await node_repo.update_node(db, root_id, {
            "sharing_mode": req.sharing_mode.value,
            "updated_at": now,
        })

    # Sync collaborators if provided
    if req.collaborators is not None:
        # Remove existing access rules (except owner)
        await db.execute(
            "DELETE FROM node_access_rules WHERE node_id = ? AND user_id != ?",
            (root_id, row["owner_user_id"]),
        )

        # Add new collaborators
        for collab in req.collaborators:
            # Resolve email to user_id
            cursor = await db.execute(
                "SELECT user_id FROM users WHERE email = ?", (collab.email,)
            )
            user_row = await cursor.fetchone()
            if user_row is None:
                continue  # skip unknown users

            collab_user_id = user_row[0]
            if collab_user_id == row["owner_user_id"]:
                continue  # skip owner

            access_level = ROLE_TO_ACCESS.get(
                collab.role, AccessLevel.USER
            ).value

            await db.execute(
                """INSERT INTO node_access_rules (node_id, user_id, access_level, created_at)
                   VALUES (?, ?, ?, ?)""",
                (root_id, collab_user_id, access_level, now),
            )

    await db.commit()

    # Re-fetch the node to build response
    updated_row = await node_repo.get_node(db, root_id)
    return await _build_sharing_response(db, updated_row, user_id, requested_node_id=node_id)


# ---------------------------------------------------------------------------
# set_sharing_batch
# ---------------------------------------------------------------------------

async def set_sharing_batch(db, user_id: str, node_ids: list[str], req) -> list[dict]:
    """Apply sharing settings to distinct graph roots for the supplied nodes."""
    results = []
    seen_roots: set[str] = set()
    for nid in node_ids:
        root_id = await node_repo.find_root_node_id(db, nid) or nid
        if root_id in seen_roots:
            continue
        seen_roots.add(root_id)
        result = await set_sharing(db, user_id, nid, req)
        results.append(result)
    return results
