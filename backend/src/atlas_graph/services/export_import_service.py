"""
Export / Import service -- serialise a subgraph for portability and
re-import with full ID remapping.

The export format uses internal/interchange field names (``node_type``,
``incoming_ids``, ``outgoing_ids``) for stable graph portability.
Import accepts both internal and API-facing aliases (``kind``, ``parent_ids``,
``child_ids``) for backwards compatibility.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from atlas_graph.auth.access_check import require_node_access
from atlas_graph.db.repos import node_repo, edge_repo
from atlas_graph.services.slug_generator import generate_slug


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


# ---------------------------------------------------------------------------
# export_subgraph
# ---------------------------------------------------------------------------

async def _expand_node_ids(
    db,
    user_id: str,
    node_ids: list[str],
    include_descendants: bool,
    max_nodes: int | None,
    skip_access_check: bool = False,
) -> list[str]:
    if not node_ids:
        return []
    if max_nodes is not None and max_nodes < 1:
        raise ValueError("max_nodes must be at least 1")

    ordered: list[str] = []
    seen: set[str] = set()
    queue = list(node_ids)

    if not skip_access_check:
        for nid in node_ids:
            await require_node_access(db, user_id, nid, "view")

    while queue:
        current = queue.pop(0)
        if current in seen:
            continue
        if max_nodes is not None and len(ordered) >= max_nodes:
            raise ValueError(f"export would exceed max_nodes={max_nodes}")
        if not skip_access_check:
            await require_node_access(db, user_id, current, "view")
        seen.add(current)
        ordered.append(current)

        if include_descendants:
            for child_id in await edge_repo.get_children(db, current):
                if child_id not in seen:
                    queue.append(child_id)

    return ordered


async def export_subgraph(
    db,
    user_id: str,
    node_ids: list[str],
    include_descendants: bool = True,
    max_nodes: int | None = None,
    skip_access_check: bool = False,
) -> dict:
    """
    Export a set of nodes (and the edges between them) into a portable dict.

    Returns a dict with:
      - version: 1
      - exported_at: timestamp
      - node_count: int
      - nodes: list of node dicts using INTERNAL field names
    """
    now = _now()
    exported_nodes: list[dict[str, Any]] = []
    ordered_node_ids = await _expand_node_ids(
        db,
        user_id,
        node_ids,
        include_descendants=include_descendants,
        max_nodes=max_nodes,
        skip_access_check=skip_access_check,
    )
    node_id_set = set(ordered_node_ids)

    for nid in ordered_node_ids:
        row = await node_repo.get_node(db, nid)
        if row is None:
            continue

        parent_ids = await edge_repo.get_parents(db, nid)
        child_ids = await edge_repo.get_children(db, nid)

        # Only include edges that point to nodes within the export set
        incoming = [pid for pid in parent_ids if pid in node_id_set]
        outgoing = [cid for cid in child_ids if cid in node_id_set]

        insights_raw = row.get("insights", "[]")
        if isinstance(insights_raw, str):
            try:
                insights = json.loads(insights_raw)
            except (json.JSONDecodeError, TypeError):
                insights = []
        else:
            insights = insights_raw or []

        # Count hidden edges (edges pointing outside the export set)
        hidden_incoming = len([pid for pid in parent_ids if pid not in node_id_set])
        hidden_outgoing = len([cid for cid in child_ids if cid not in node_id_set])

        # Look up owner email
        owner_user_id = row.get("owner_user_id")
        owner_email = None
        if owner_user_id:
            cursor = await db.execute(
                "SELECT email FROM users WHERE user_id = ?", (owner_user_id,)
            )
            owner_row = await cursor.fetchone()
            if owner_row:
                owner_email = owner_row[0]

        exported_nodes.append({
            "node_id": nid,
            "slug_name": row.get("slug_name"),
            "title": row.get("title"),
            "summary": row.get("summary") or "",
            "content": row.get("content") or "",
            "node_type": row.get("node_type", "untyped"),
            "lifecycle": row.get("lifecycle", "staged"),
            "outcome": row.get("outcome"),
            "hypothesis": row.get("hypothesis") or "",
            "no_artifacts_reason": row.get("no_artifacts_reason"),
            "insights": insights,
            "incoming_ids": incoming,
            "outgoing_ids": outgoing,
            "hidden_incoming_count": hidden_incoming,
            "hidden_outgoing_count": hidden_outgoing,
            "home_domain": row.get("origin_host"),
            "owner_email": owner_email,
            "repo_url": row.get("repo_url"),
            "branch_name": row.get("branch_name"),
            "head_commit_sha": row.get("head_commit_sha"),
            "origin_host": row.get("origin_host"),
            "run_data": row.get("run_data"),
            "semantic_data": row.get("semantic_data"),
            "updated_by": row.get("updated_by"),
            "external_transcript_ref": row.get("external_transcript_ref"),
            "revision": row.get("revision", 0),
            "created_at": row.get("created_at", ""),
            "updated_at": row.get("updated_at", ""),
        })

    return {
        "version": 1,
        "exported_at": now,
        "node_count": len(exported_nodes),
        "include_descendants": include_descendants,
        "max_nodes": max_nodes,
        "nodes": exported_nodes,
    }


async def export_history(
    db,
    user_id: str,
    node_ids: list[str],
    include_descendants: bool = False,
    max_nodes: int | None = 200,
    limit_per_node: int = 50,
) -> dict:
    """Export audit/revision history for nodes in a portable JSON shape."""
    if limit_per_node < 1:
        raise ValueError("limit_per_node must be at least 1")

    ordered_node_ids = await _expand_node_ids(
        db,
        user_id,
        node_ids,
        include_descendants=include_descendants,
        max_nodes=max_nodes,
    )
    nodes = await node_repo.get_nodes_by_ids(db, ordered_node_ids)
    histories: list[dict[str, Any]] = []

    for node_id in ordered_node_ids:
        row = nodes.get(node_id)
        cursor = await db.execute(
            """SELECT event_id, actor_user_id, oauth_client_id, node_id,
                      operation, idempotency_key, expected_revision,
                      result_revision, request_hash, timestamp
               FROM audit_events
               WHERE node_id = ?
               ORDER BY timestamp DESC
               LIMIT ?""",
            (node_id, limit_per_node),
        )
        columns = [desc[0] for desc in cursor.description]
        events = [dict(zip(columns, r)) for r in await cursor.fetchall()]
        histories.append({
            "node_id": node_id,
            "revision": row.get("revision", 0) if row else 0,
            "events": events,
            "event_count": len(events),
        })

    return {
        "version": 1,
        "exported_at": _now(),
        "node_count": len(histories),
        "nodes": histories,
    }


# ---------------------------------------------------------------------------
# import_subgraph
# ---------------------------------------------------------------------------

async def import_subgraph(db, user_id: str, data: dict) -> dict:
    """
    Import a previously-exported subgraph.

    Accepts the internal field names (node_type, incoming_ids, outgoing_ids)
    as produced by ``export_subgraph``.  Also tolerates the API-facing aliases
    (``kind`` for ``node_type``, ``parent_ids`` for ``incoming_ids``,
    ``child_ids`` for ``outgoing_ids``) so callers do not need to know which
    format was used.

    Generates new node IDs for every imported node and remaps all edges.

    Returns a dict with:
      - imported_count: int
      - id_mapping: dict mapping old_id -> new_id
      - skipped: list of indices where node_id was missing
    """
    data = _unwrap_import_payload(data)
    nodes = data.get("nodes", [])
    now = _now()

    # Build ID mapping: old -> new  (skip entries without a usable ID)
    id_map: dict[str, str] = {}
    skipped: list[int] = []
    for idx, node in enumerate(nodes):
        old_id = node.get("node_id") or node.get("id")
        if not old_id:
            skipped.append(idx)
            continue
        id_map[old_id] = str(uuid.uuid4())

    # Create all nodes with new IDs
    for idx, node in enumerate(nodes):
        old_id = node.get("node_id") or node.get("id")
        if not old_id or old_id not in id_map:
            continue
        new_id = id_map[old_id]
        slug = await generate_slug(db)

        # Accept both internal names (node_type) and API names (kind)
        node_type = node.get("node_type") or node.get("kind", "untyped")

        node_data = {
            "node_id": new_id,
            "owner_user_id": user_id,
            "slug_name": slug,
            "title": node.get("title"),
            "summary": node.get("summary"),
            "content": node.get("content"),
            "node_type": node_type,
            "lifecycle": node.get("lifecycle", "staged"),
            "outcome": node.get("outcome"),
            "hypothesis": node.get("hypothesis"),
            "no_artifacts_reason": node.get("no_artifacts_reason"),
            "insights": json.dumps(node.get("insights", [])),
            "repo_url": node.get("repo_url"),
            "branch_name": node.get("branch_name"),
            "head_commit_sha": node.get("head_commit_sha"),
            "origin_host": node.get("origin_host"),
            "updated_by": node.get("updated_by"),
            "external_transcript_ref": node.get("external_transcript_ref"),
            "revision": 0,
            "sharing_mode": "private",
            "created_at": now,
            "updated_at": now,
        }
        await node_repo.create_node(db, node_data)
        extra: dict[str, Any] = {}
        if node.get("run_data") is not None:
            extra["run_data"] = node.get("run_data") if isinstance(node.get("run_data"), str) else json.dumps(node.get("run_data"))
        if node.get("semantic_data") is not None:
            extra["semantic_data"] = node.get("semantic_data") if isinstance(node.get("semantic_data"), str) else json.dumps(node.get("semantic_data"))
        if extra:
            await node_repo.update_node(db, new_id, extra)

    # Create edges with remapped IDs
    # Accept both internal names (incoming_ids/outgoing_ids) and API names
    # (parent_ids/child_ids).
    edges_created: set[tuple[str, str]] = set()
    for node in nodes:
        old_id = node.get("node_id") or node.get("id")
        if not old_id or old_id not in id_map:
            continue
        new_id = id_map[old_id]

        # incoming_ids (internal) / parent_ids (API) = parent IDs
        incoming = node.get("incoming_ids") or node.get("parent_ids") or []
        for old_parent_id in incoming:
            new_parent_id = id_map.get(old_parent_id)
            if new_parent_id and (new_parent_id, new_id) not in edges_created:
                await edge_repo.add_edge(db, new_parent_id, new_id, now)
                edges_created.add((new_parent_id, new_id))

        # outgoing_ids (internal) / child_ids (API) = child IDs
        outgoing = node.get("outgoing_ids") or node.get("child_ids") or []
        for old_child_id in outgoing:
            new_child_id = id_map.get(old_child_id)
            if new_child_id and (new_id, new_child_id) not in edges_created:
                await edge_repo.add_edge(db, new_id, new_child_id, now)
                edges_created.add((new_id, new_child_id))

    await db.commit()

    return {
        "imported_count": len(id_map),
        "node_ids": list(id_map.values()),
        "id_mapping": id_map,
        "skipped": skipped,
        "normalized_cycle_edges_removed": 0,
    }


def _unwrap_import_payload(data: dict) -> dict:
    """Accept raw export payloads or common wrapper keys used by clients."""
    if not isinstance(data, dict):
        raise ValueError("Import payload must be an object")
    for key in ("payload", "export", "subgraph", "data"):
        wrapped = data.get(key)
        if isinstance(wrapped, dict) and "nodes" in wrapped:
            return wrapped
    return data
