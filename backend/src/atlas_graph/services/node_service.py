"""
Core node service -- the engine for creating, updating, committing, branching,
merging, and deleting research-graph nodes.

Every public function takes an aiosqlite connection as its first ``db`` arg.
"""

from __future__ import annotations

import asyncio
import http.client
import ipaddress
import json
import socket
import ssl
import threading
import time
import urllib.parse
import uuid
from datetime import datetime
from typing import Any

from atlas_graph import config
from atlas_graph.auth.access_check import check_node_access, require_node_access
from atlas_graph.db.transaction import transaction
from atlas_graph.db.repos import node_repo, edge_repo, tag_repo, artifact_repo
from atlas_graph.models.node import (
    BranchNodeRequest,
    CommitNodeRequest,
    MergeNodesRequest,
    StageNodeCreateRequest,
    StageNodeUpdateRequest,
    AddParentRequest,
    RemoveParentRequest,
)
from atlas_graph.realtime.event_broadcaster import on_node_mutated, on_node_deleted
from atlas_graph.services.slug_generator import generate_slug


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _parse_cursor(cursor: str | None) -> int:
    if cursor in (None, ""):
        return 0
    try:
        offset = int(str(cursor))
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid cursor") from exc
    if offset < 0:
        raise ValueError("Invalid cursor")
    return offset


def _page_info(offset: int, limit: int, total: int) -> dict[str, Any]:
    end = min(offset + limit, total)
    has_next_page = end < total
    return {
        "start_cursor": str(offset) if total else None,
        "end_cursor": str(end) if has_next_page else None,
        "has_next_page": has_next_page,
        "has_previous_page": offset > 0,
    }


def _json_loads(value: Any, fallback: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return fallback
    return value if value is not None else fallback


def _get_dotted(value: Any, path: str) -> Any:
    if path in ("", "."):
        return value
    current = value
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return current


def _serialize_artifact_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_id": row["artifact_id"],
        "node_id": row["node_id"],
        "artifact_type": row["artifact_type"],
        "title": row["title"],
        "note": row.get("note"),
        "payload": _json_loads(row.get("payload"), {}),
        "metadata": _json_loads(row.get("metadata"), {}),
        "execution_id": row.get("execution_id"),
        "storage_path": row.get("storage_path") or "",
        "created_at": row.get("created_at", ""),
    }


async def _get_contract_warnings(db, node_row: dict) -> list[dict[str, str]]:
    """
    Check whether a future commit would fail given the current staged state.
    Returns a list of warning dicts with 'code' and 'message' keys.
    """
    warnings: list[dict[str, str]] = []

    kind = node_row.get("node_type", "untyped")
    outcome = node_row.get("outcome")
    no_artifacts_reason = node_row.get("no_artifacts_reason")

    # Check artifact count for this node
    if kind == "empirical" and outcome == "completed":
        cursor = await db.execute(
            "SELECT COUNT(*) FROM artifacts WHERE node_id = ?",
            (node_row["node_id"],),
        )
        artifact_count = (await cursor.fetchone())[0]

        if artifact_count == 0 and not no_artifacts_reason:
            warnings.append({
                "code": "empirical_completed_requires_artifacts_or_reason",
                "message": (
                    "Empirical nodes with outcome=completed must have at least "
                    "one artifact or a no_artifacts_reason."
                ),
            })

    return warnings


def _build_node_response(
    row: dict,
    parent_ids: list[str],
    child_ids: list[str],
    graph_tags: list[dict] | None = None,
    tag_ids: list[str] | None = None,
    tag_history: list[dict] | None = None,
) -> dict:
    """
    Transform a raw DB row + topology into a Node-compatible dict.

    The DB stores ``node_type`` but the API exposes ``kind``.
    """
    insights_raw = row.get("insights", "[]")
    if isinstance(insights_raw, str):
        try:
            insights = json.loads(insights_raw)
        except (json.JSONDecodeError, TypeError):
            insights = []
    else:
        insights = insights_raw or []

    return {
        "node_id": row["node_id"],
        "slug_name": row.get("slug_name"),
        "title": row.get("title"),
        "summary": row.get("summary") or "",
        "content": row.get("content") or "",
        "updated_by": row.get("updated_by"),
        "kind": row.get("node_type", "untyped"),
        "lifecycle": row.get("lifecycle", "staged"),
        "outcome": row.get("outcome"),
        "hypothesis": row.get("hypothesis") or "",
        "no_artifacts_reason": row.get("no_artifacts_reason"),
        "insights": insights,
        "parent_ids": parent_ids,
        "child_ids": child_ids,
        "repo_url": row.get("repo_url"),
        "branch_name": row.get("branch_name"),
        "head_commit_sha": row.get("head_commit_sha"),
        "origin_host": row.get("origin_host"),
        "external_transcript_ref": row.get("external_transcript_ref"),
        "revision": row.get("revision", 0),
        "sharing_mode": row.get("sharing_mode", "private"),
        # Research semantic layer (scorecards, optimize_run state, plan/
        # hypothesis bindings). Parsed defensively; None when absent so the
        # payload stays light for untyped nodes.
        "semantic_data": parse_node_semantics(row) or None,
        "graph_tags": [
            {
                **tag,
                "one_only": bool(tag.get("one_only", 0)),
                "track_history": bool(tag.get("track_history", 0)),
            }
            for tag in (graph_tags or [])
        ],
        "tag_ids": tag_ids or [],
        "tag_history": tag_history or [],
        "created_at": row.get("created_at", ""),
        "updated_at": row.get("updated_at", ""),
    }


async def _full_node_response(db, node_id: str, user_id: str | None = None) -> dict:
    """Fetch a node row + its topology and return a Node-compatible dict.

    When *user_id* is provided the response is enriched with ownership and
    visibility fields (``is_owner``, ``visibility``, ``can_write``,
    ``can_admin``, ``owner_email``, ``artifacts_total``,
    ``artifacts_truncated``) so that tag and other mutation responses can
    return a complete Atlas node shape.
    """
    row = await node_repo.get_node(db, node_id)
    if row is None:
        raise ValueError(f"Node {node_id} not found")
    parent_ids = await edge_repo.get_parents(db, node_id)
    child_ids = await edge_repo.get_children(db, node_id)

    # Look up root to get tags
    root_id = await node_repo.find_root_node_id(db, node_id)
    graph_tags = await tag_repo.get_tags_for_root(db, root_id) if root_id else []
    tag_assignments = await tag_repo.get_tag_assignments(db, node_id)
    tag_ids = [ta["tag_id"] for ta in tag_assignments] if tag_assignments else []
    tag_history = await tag_repo.get_tag_history_for_node(db, node_id)

    warnings = await _get_contract_warnings(db, row)
    result = _build_node_response(row, parent_ids, child_ids, graph_tags, tag_ids, tag_history)
    result["contract_warnings"] = warnings

    # Enrich with ownership / visibility when caller identity is known
    if user_id is not None:
        owner_user_id = row.get("owner_user_id")
        is_owner = owner_user_id == user_id

        result["is_owner"] = is_owner
        result["can_write"] = is_owner
        result["can_admin"] = is_owner

        # Owner email
        cursor = await db.execute(
            "SELECT email FROM users WHERE user_id = ?", (owner_user_id,)
        )
        owner_row = await cursor.fetchone()
        result["owner_email"] = owner_row[0] if owner_row else ""

        # Visibility
        sharing_mode = row.get("sharing_mode", "private")
        if sharing_mode == "public":
            result["visibility"] = "public"
        elif sharing_mode == "unlisted":
            result["visibility"] = "unlisted"
        else:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM node_access_rules WHERE node_id = ?",
                (node_id,),
            )
            collab_count = (await cursor.fetchone())[0]
            result["visibility"] = "shared" if collab_count > 0 else "private"

        # Access level for non-owners
        if not is_owner:
            cursor = await db.execute(
                "SELECT access_level FROM node_access_rules WHERE node_id = ? AND user_id = ?",
                (node_id, user_id),
            )
            access_row = await cursor.fetchone()
            if access_row:
                level = access_row[0]
                result["can_write"] = level in ("USER_WRITE", "USER_ADMIN")
                result["can_admin"] = level == "USER_ADMIN"
            else:
                result["can_write"] = False
                result["can_admin"] = False

        # Artifact counts
        cursor = await db.execute(
            "SELECT COUNT(*) FROM artifacts WHERE node_id = ?", (node_id,)
        )
        result["artifacts_total"] = (await cursor.fetchone())[0]
        result["artifacts_truncated"] = False

    # Include full projection fields used by the Atlas CLI.
    result["graph_projection"] = "full"
    result["artifacts"] = []
    result["executions"] = []

    return result


# ---------------------------------------------------------------------------
# stage_create
# ---------------------------------------------------------------------------

async def stage_create(db, user_id: str, req: StageNodeCreateRequest) -> dict:
    """Create a new staged node."""
    async with transaction(db) as connection:
        for parent_id in req.parent_ids or []:
            await require_node_access(connection, user_id, parent_id, "write")
        node_id = str(uuid.uuid4())
        slug = await generate_slug(connection)
        now = _now()

        node_data = {
            "node_id": node_id,
            "owner_user_id": user_id,
            "slug_name": slug,
            "title": req.title,
            "summary": req.summary,
            "content": req.content,
            "node_type": req.kind.value if req.kind is not None else "untyped",
            "lifecycle": "staged",
            "outcome": None,
            "hypothesis": req.hypothesis,
            "no_artifacts_reason": None,
            "insights": "[]",
            "repo_url": req.repo_url,
            "branch_name": req.branch_name,
            "head_commit_sha": req.head_commit_sha,
            "origin_host": req.origin_host,
            "updated_by": req.updated_by,
            "external_transcript_ref": req.external_transcript_ref,
            "revision": 0,
            "sharing_mode": "private",
            "created_at": now,
            "updated_at": now,
        }
        await node_repo.create_node(connection, node_data)

        # Add edges for parent_ids
        if req.parent_ids:
            for pid in req.parent_ids:
                await edge_repo.add_edge(connection, pid, node_id, now)

    result = await _full_node_response(db, node_id)
    try:
        await on_node_mutated(node_id, "created", result)
    except Exception:
        pass
    return result


# ---------------------------------------------------------------------------
# stage_update
# ---------------------------------------------------------------------------

async def stage_update(db, user_id: str, req: StageNodeUpdateRequest) -> dict:
    """
    Update a staged node with optimistic concurrency control.
    Rejects if expected_revision doesn't match (409 equivalent).
    """
    await require_node_access(db, user_id, req.node_id, "write")

    row = await node_repo.get_node(db, req.node_id)
    if row is None:
        raise ValueError(f"Node {req.node_id} not found")

    if row["revision"] != req.expected_revision:
        raise ValueError(
            f"409 conflict: expected revision {req.expected_revision}, "
            f"current is {row['revision']}"
        )

    now = _now()
    updates: dict[str, Any] = {"updated_at": now}

    if req.title is not None:
        updates["title"] = req.title
    if req.summary is not None:
        updates["summary"] = req.summary
    if req.content is not None:
        updates["content"] = req.content
    if req.kind is not None:
        updates["node_type"] = req.kind.value
    if req.outcome is not None:
        updates["outcome"] = req.outcome.value
    if req.hypothesis is not None:
        updates["hypothesis"] = req.hypothesis
    if req.no_artifacts_reason is not None:
        updates["no_artifacts_reason"] = req.no_artifacts_reason
    if req.insights is not None:
        updates["insights"] = json.dumps(req.insights)
    if req.updated_by is not None:
        updates["updated_by"] = req.updated_by
    if req.repo_url is not None:
        updates["repo_url"] = req.repo_url
    if req.branch_name is not None:
        updates["branch_name"] = req.branch_name
    if req.head_commit_sha is not None:
        updates["head_commit_sha"] = req.head_commit_sha
    if req.origin_host is not None:
        updates["origin_host"] = req.origin_host
    if req.external_transcript_ref is not None:
        updates["external_transcript_ref"] = req.external_transcript_ref

    # Increment revision — guard the write on the revision we just read so a
    # concurrent staged-update can't silently clobber this one (the read-check
    # above is not atomic with the write).
    new_revision = row["revision"] + 1
    updates["revision"] = new_revision

    updated = await node_repo.update_node(
        db, req.node_id, updates, expected_revision=req.expected_revision
    )
    if updated is None:
        raise ValueError(
            "409 conflict: node was modified concurrently; refetch and retry"
        )
    await db.commit()

    result = await _full_node_response(db, req.node_id)
    try:
        await on_node_mutated(req.node_id, "updated", result)
    except Exception:
        pass
    return result


# ---------------------------------------------------------------------------
# commit_node
# ---------------------------------------------------------------------------

async def commit_node(db, user_id: str, req: CommitNodeRequest) -> dict | None:
    """
    Commit a staged node.  Strict OCC: if expected_revision doesn't match,
    return None (silent failure).

    Validation rules (all must pass or return None silently):
    - kind != 'untyped'
    - outcome must be set
    - summary must be set (or provided in req.summary)
    - If insight: insights must be non-empty
    - If empirical: hypothesis must be non-empty, insights must be empty
    - If empirical + completed: must have artifacts OR no_artifacts_reason
    """
    await require_node_access(db, user_id, req.node_id, "write")

    row = await node_repo.get_node(db, req.node_id)
    if row is None:
        return None

    # Strict OCC
    if row["revision"] != req.expected_revision:
        return None

    # Apply summary if provided in request
    summary = row.get("summary")
    if req.summary is not None:
        summary = req.summary

    kind = row.get("node_type", "untyped")
    outcome = row.get("outcome")
    hypothesis = row.get("hypothesis")
    no_artifacts_reason = row.get("no_artifacts_reason")

    insights_raw = row.get("insights", "[]")
    if isinstance(insights_raw, str):
        try:
            insights = json.loads(insights_raw)
        except (json.JSONDecodeError, TypeError):
            insights = []
    else:
        insights = insights_raw or []

    # Validation: kind != untyped
    if kind == "untyped":
        return None

    # Validation: outcome must be set
    if not outcome:
        return None

    # Validation: summary must be set
    if not summary:
        return None

    # Validation: insight -> insights non-empty
    if kind == "insight" and (not insights or len(insights) == 0):
        return None

    # Validation: empirical -> hypothesis non-empty, insights must be empty
    if kind == "empirical":
        if not hypothesis:
            return None
        if insights and len(insights) > 0:
            return None

    # Validation: empirical + completed -> artifacts or no_artifacts_reason
    if kind == "empirical" and outcome == "completed":
        cursor = await db.execute(
            "SELECT COUNT(*) FROM artifacts WHERE node_id = ?", (req.node_id,)
        )
        artifact_count = (await cursor.fetchone())[0]
        if artifact_count == 0 and not no_artifacts_reason:
            return None

    now = _now()
    new_revision = row["revision"] + 1

    updates = {
        "lifecycle": "committed",
        "revision": new_revision,
        "updated_at": now,
    }
    if req.summary is not None:
        updates["summary"] = req.summary

    # Atomic OCC: only commit if the revision still matches what we validated.
    committed = await node_repo.update_node(
        db, req.node_id, updates, expected_revision=req.expected_revision
    )
    if committed is None:
        raise ValueError(
            "409 conflict: node was modified concurrently; refetch and retry"
        )
    await db.commit()

    result = await _full_node_response(db, req.node_id)
    try:
        await on_node_mutated(req.node_id, "committed", result)
    except Exception:
        pass
    return result


# ---------------------------------------------------------------------------
# Semantic layer column writes
# ---------------------------------------------------------------------------

def parse_node_semantics(row: dict[str, Any] | None) -> dict[str, Any]:
    """Defensively deserialise a node row's ``semantic_data`` column.

    Bad / missing JSON yields ``{}`` so readers (brief, runs:compare)
    can treat any node as "no semantics" instead of failing the whole
    response on one corrupt row.
    """
    raw = (row or {}).get("semantic_data")
    if raw is None:
        return {}
    if isinstance(raw, dict):
        # asyncpg may hand JSONB back already-decoded depending on codecs.
        return raw
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


async def apply_semantics(
    db,
    node_id: str,
    semantic_data: dict[str, Any] | None,
    extra_cols: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Write the research-verb payload (and any extra direct columns)
    onto a node row, post-commit.

    These columns aren't in StageNodeUpdateRequest on purpose - callers
    should always reach them through the semantic-layer / Flight
    Recorder routes. Returns the refreshed row (or ``None`` if the node
    vanished).
    """
    fields: dict[str, Any] = dict(extra_cols or {})
    if semantic_data is not None:
        fields["semantic_data"] = json.dumps(semantic_data)
    if fields:
        await node_repo.update_node(db, node_id, fields)
        await db.commit()
    return await node_repo.get_node(db, node_id)


# ---------------------------------------------------------------------------
# branch_node
# ---------------------------------------------------------------------------

async def branch_node(db, user_id: str, req: BranchNodeRequest) -> dict:
    """
    Create a new child node branching from an existing node.

    - Increment PARENT revision.
    - Child starts at revision 0, kind=untyped, lifecycle=staged.
    """
    async with transaction(db) as connection:
        await require_node_access(connection, user_id, req.node_id, "write")

        parent_row = await node_repo.get_node(connection, req.node_id)
        if parent_row is None:
            raise ValueError(f"Node {req.node_id} not found")
        if parent_row["revision"] != req.expected_revision:
            raise ValueError(
                f"409 conflict: expected revision {req.expected_revision}, "
                f"current is {parent_row['revision']}"
            )

        # Increment parent revision
        parent_new_revision = parent_row["revision"] + 1
        now = _now()
        updated = await node_repo.update_node(connection, req.node_id, {
            "revision": parent_new_revision,
            "updated_at": now,
        }, expected_revision=req.expected_revision)
        if updated is None:
            raise ValueError("409 conflict: node was modified concurrently; refetch and retry")

        # Create child node
        child_id = str(uuid.uuid4())
        slug = await generate_slug(connection)

        child_data = {
            "node_id": child_id,
            "owner_user_id": user_id,
            "slug_name": slug,
            "title": req.title,
            "summary": parent_row.get("summary"),
            "content": parent_row.get("content"),
            "node_type": "untyped",
            "lifecycle": "staged",
            "outcome": None,
            "hypothesis": None,
            "no_artifacts_reason": None,
            "insights": "[]",
            "repo_url": parent_row.get("repo_url"),
            "branch_name": parent_row.get("branch_name"),
            "head_commit_sha": parent_row.get("head_commit_sha"),
            "origin_host": parent_row.get("origin_host"),
            "updated_by": user_id,
            "external_transcript_ref": None,
            "revision": 0,
            "sharing_mode": parent_row.get("sharing_mode", "private"),
            "created_at": now,
            "updated_at": now,
        }
        await node_repo.create_node(connection, child_data)
        parent_semantics = parse_node_semantics(parent_row)
        branch_semantics: dict[str, Any] = {
            "type": "branch",
            "branched_from_node_id": req.node_id,
            "branched_from_revision": parent_row.get("revision"),
        }
        if isinstance(parent_semantics.get("code_state"), dict):
            branch_semantics["code_state"] = parent_semantics["code_state"]
        await node_repo.update_node(connection, child_id, {"semantic_data": json.dumps(branch_semantics)})
        await edge_repo.add_edge(connection, req.node_id, child_id, now)

    child_resp = await _full_node_response(db, child_id)
    try:
        await on_node_mutated(child_id, "created", child_resp)
        parent_resp = await _full_node_response(db, req.node_id)
        await on_node_mutated(req.node_id, "branched", parent_resp)
    except Exception:
        pass
    return {
        "node": child_resp,
        "parent_revision": parent_new_revision,
    }


# ---------------------------------------------------------------------------
# merge_nodes
# ---------------------------------------------------------------------------

async def merge_nodes(db, user_id: str, req: MergeNodesRequest) -> dict:
    """
    Merge multiple nodes into a single resolved node.

    Creates a new node with data from ``req.resolved_node`` and edges from
    all the source nodes' parents.  Source nodes are not deleted.
    """
    # Require write access to all source nodes
    source_rows: dict[str, dict[str, Any]] = {}
    for nid in req.node_ids:
        await require_node_access(db, user_id, nid, "write")
        row = await node_repo.get_node(db, nid)
        if row is None:
            raise ValueError(f"Node {nid} not found")
        source_rows[nid] = row
        expected = req.expected_revision_by_node.get(nid)
        if expected is None:
            raise ValueError(f"Missing expected revision for node {nid}")
        if row["revision"] != expected:
            raise ValueError(
                f"409 conflict for node {nid}: expected revision {expected}, "
                f"current is {row['revision']}"
            )

    now = _now()
    merged_id = str(uuid.uuid4())
    slug = await generate_slug(db)

    resolved = req.resolved_node
    merged_data = {
        "node_id": merged_id,
        "owner_user_id": user_id,
        "slug_name": slug,
        "title": resolved.get("title"),
        "summary": resolved.get("summary"),
        "content": resolved.get("content"),
        "node_type": resolved.get("kind", "untyped"),
        "lifecycle": resolved.get("lifecycle", "staged"),
        "outcome": resolved.get("outcome"),
        "hypothesis": resolved.get("hypothesis"),
        "no_artifacts_reason": resolved.get("no_artifacts_reason"),
        "insights": json.dumps(resolved.get("insights", [])),
        "repo_url": resolved.get("repo_url"),
        "branch_name": resolved.get("branch_name"),
        "head_commit_sha": resolved.get("head_commit_sha"),
        "origin_host": resolved.get("origin_host"),
        "updated_by": resolved.get("updated_by"),
        "external_transcript_ref": resolved.get("external_transcript_ref"),
        "revision": 0,
        "sharing_mode": "private",
        "created_at": now,
        "updated_at": now,
    }
    await node_repo.create_node(db, merged_data)

    # Batch-fetch parents for all source nodes in one query
    parents_map, _ = await edge_repo.get_edges_for_nodes(db, req.node_ids)
    all_parents: set[str] = set()
    for nid in req.node_ids:
        all_parents.update(parents_map.get(nid, []))
    # Don't add an edge to any of the source nodes themselves
    all_parents -= set(req.node_ids)

    for pid in all_parents:
        await edge_repo.add_edge(db, pid, merged_id, now)

    # Source nodes become parents of the merged node as well
    for nid in req.node_ids:
        await edge_repo.add_edge(db, nid, merged_id, now)
        await node_repo.update_node(db, nid, {
            "revision": source_rows[nid]["revision"] + 1,
            "updated_at": now,
        })

    await db.commit()
    return await _full_node_response(db, merged_id)


# ---------------------------------------------------------------------------
# delete_node
# ---------------------------------------------------------------------------

async def delete_node(
    db, user_id: str, node_id: str, delete_mode: str = "detach_shared"
) -> None:
    """
    Delete a node.

    - cascade: delete node + all descendants
    - detach_shared: delete only this node, reconnect children to parents
    """
    await require_node_access(db, user_id, node_id, "admin")

    row = await node_repo.get_node(db, node_id)
    if row is None:
        raise ValueError(f"Node {node_id} not found")

    if delete_mode == "detach_shared":
        parent_ids = await edge_repo.get_parents(db, node_id)
        child_ids = await edge_repo.get_children(db, node_id)
        now = _now()

        # Reconnect children to parents
        for cid in child_ids:
            for pid in parent_ids:
                try:
                    await edge_repo.add_edge(db, pid, cid, now)
                except Exception:
                    pass  # edge may already exist

        # Delete this node (cascade will remove its edges)
        await node_repo.delete_node(db, node_id)

    elif delete_mode == "cascade":
        # Collect all descendants via BFS
        to_delete = set()
        queue = [node_id]
        while queue:
            current = queue.pop(0)
            if current in to_delete:
                continue
            to_delete.add(current)
            children = await edge_repo.get_children(db, current)
            for cid in children:
                if cid not in to_delete:
                    queue.append(cid)

        # Delete all in reverse (leaves first doesn't matter with CASCADE)
        for nid in to_delete:
            await node_repo.delete_node(db, nid)
    else:
        raise ValueError(f"Unsupported delete_mode {delete_mode!r}")

    await db.commit()

    try:
        await on_node_deleted(node_id)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# bulk_delete_nodes
# ---------------------------------------------------------------------------

async def bulk_delete_nodes(
    db, user_id: str, node_ids: list[str], delete_mode: str = "detach_shared"
) -> dict:
    """
    Delete multiple nodes. Nodes are deleted when the user has graph-admin
    access, matching ``delete_node``; others are skipped. Returns a
    BulkDeleteResponse dict.
    """
    deleted_ids: list[str] = []
    skipped: list[str] = []
    seen_deleted: set[str] = set()

    if delete_mode not in {"cascade", "detach_shared"}:
        raise ValueError(f"Unsupported delete_mode {delete_mode!r}")

    for nid in node_ids:
        row = await node_repo.get_node(db, nid)
        if row is None:
            skipped.append(nid)
            continue
        try:
            await require_node_access(db, user_id, nid, "admin")
        except Exception:
            skipped.append(nid)
            continue

        before = set()
        if delete_mode == "cascade":
            queue = [nid]
            while queue:
                current = queue.pop(0)
                if current in before:
                    continue
                before.add(current)
                children = await edge_repo.get_children(db, current)
                for cid in children:
                    if cid not in before:
                        queue.append(cid)
        else:
            before.add(nid)

        await delete_node(db, user_id, nid, delete_mode=delete_mode)
        for did in before:
            if did not in seen_deleted and await node_repo.get_node(db, did) is None:
                seen_deleted.add(did)
                deleted_ids.append(did)

    await db.commit()

    return {
        "success": True,
        "deleted_count": len(deleted_ids),
        "deleted_node_ids": deleted_ids,
        "skipped_non_owned": skipped,
        "graph_event_id": str(uuid.uuid4()),
    }


# ---------------------------------------------------------------------------
# add_parent
# ---------------------------------------------------------------------------

async def add_parent(db, user_id: str, req: AddParentRequest) -> dict:
    """
    Add a parent edge.

    Checks both expected_revision and expected_parent_revision.
    Checks for cycles before adding edge.
    Increments BOTH node and parent revision.
    """
    await require_node_access(db, user_id, req.node_id, "write")
    await require_node_access(db, user_id, req.parent_id, "write")

    node_row = await node_repo.get_node(db, req.node_id)
    if node_row is None:
        raise ValueError(f"Node {req.node_id} not found")
    parent_row = await node_repo.get_node(db, req.parent_id)
    if parent_row is None:
        raise ValueError(f"Parent node {req.parent_id} not found")

    if node_row["revision"] != req.expected_revision:
        raise ValueError(
            f"Revision mismatch for node {req.node_id}: "
            f"expected {req.expected_revision}, got {node_row['revision']}"
        )
    if parent_row["revision"] != req.expected_parent_revision:
        raise ValueError(
            f"Revision mismatch for parent {req.parent_id}: "
            f"expected {req.expected_parent_revision}, got {parent_row['revision']}"
        )

    # Check for cycles: adding parent_id -> node_id should not create a cycle
    would_cycle = await edge_repo.has_cycle(db, req.parent_id, req.node_id)
    if would_cycle:
        raise ValueError(
            f"Adding edge {req.parent_id} -> {req.node_id} would create a cycle"
        )

    now = _now()
    await edge_repo.add_edge(db, req.parent_id, req.node_id, now)

    # Increment both revisions
    node_new_rev = node_row["revision"] + 1
    parent_new_rev = parent_row["revision"] + 1
    await node_repo.update_node(db, req.node_id, {
        "revision": node_new_rev, "updated_at": now,
    })
    await node_repo.update_node(db, req.parent_id, {
        "revision": parent_new_rev, "updated_at": now,
    })

    await db.commit()
    return await _full_node_response(db, req.node_id)


# ---------------------------------------------------------------------------
# remove_parent
# ---------------------------------------------------------------------------

async def remove_parent(db, user_id: str, req: RemoveParentRequest) -> dict:
    """
    Remove a parent edge.

    Checks both expected_revision and expected_parent_revision.
    Increments BOTH node and parent revision.
    """
    await require_node_access(db, user_id, req.node_id, "write")
    await require_node_access(db, user_id, req.parent_id, "write")

    node_row = await node_repo.get_node(db, req.node_id)
    if node_row is None:
        raise ValueError(f"Node {req.node_id} not found")
    parent_row = await node_repo.get_node(db, req.parent_id)
    if parent_row is None:
        raise ValueError(f"Parent node {req.parent_id} not found")

    if node_row["revision"] != req.expected_revision:
        raise ValueError(
            f"Revision mismatch for node {req.node_id}: "
            f"expected {req.expected_revision}, got {node_row['revision']}"
        )
    if parent_row["revision"] != req.expected_parent_revision:
        raise ValueError(
            f"Revision mismatch for parent {req.parent_id}: "
            f"expected {req.expected_parent_revision}, got {parent_row['revision']}"
        )

    now = _now()
    await edge_repo.remove_edge(db, req.parent_id, req.node_id)

    # Increment both revisions
    node_new_rev = node_row["revision"] + 1
    parent_new_rev = parent_row["revision"] + 1
    await node_repo.update_node(db, req.node_id, {
        "revision": node_new_rev, "updated_at": now,
    })
    await node_repo.update_node(db, req.parent_id, {
        "revision": parent_new_rev, "updated_at": now,
    })

    await db.commit()
    return await _full_node_response(db, req.node_id)


# ---------------------------------------------------------------------------
# get_node
# ---------------------------------------------------------------------------

async def get_node(
    db, user_id: str, node_id: str, projection: str = "core"
) -> dict:
    """Fetch a single node by ID."""
    await require_node_access(db, user_id, node_id, "view")

    row = await node_repo.get_node(db, node_id)
    if row is None:
        raise ValueError(f"Node {node_id} not found")

    parent_ids = await edge_repo.get_parents(db, node_id)
    child_ids = await edge_repo.get_children(db, node_id)

    root_id = await node_repo.find_root_node_id(db, node_id)
    graph_tags = await tag_repo.get_tags_for_root(db, root_id) if root_id else []
    tag_assignments = await tag_repo.get_tag_assignments(db, node_id)
    tag_ids = [ta["tag_id"] for ta in tag_assignments] if tag_assignments else []
    tag_history = await tag_repo.get_tag_history_for_node(db, node_id)

    result = _build_node_response(row, parent_ids, child_ids, graph_tags, tag_ids, tag_history)

    # Ownership / visibility info
    is_owner = row.get("owner_user_id") == user_id
    result["is_owner"] = is_owner
    result["can_write"] = is_owner
    result["can_admin"] = is_owner

    # Determine visibility
    sharing_mode = row.get("sharing_mode", "private")
    if sharing_mode == "public":
        result["visibility"] = "public"
    elif sharing_mode == "unlisted":
        result["visibility"] = "unlisted"
    else:
        # Check for collaborators
        cursor = await db.execute(
            "SELECT COUNT(*) FROM node_access_rules WHERE node_id = ?",
            (node_id,),
        )
        collab_count = (await cursor.fetchone())[0]
        result["visibility"] = "shared" if collab_count > 0 else "private"

    # Access level for non-owners
    if not is_owner:
        cursor = await db.execute(
            "SELECT access_level FROM node_access_rules WHERE node_id = ? AND user_id = ?",
            (node_id, user_id),
        )
        access_row = await cursor.fetchone()
        if access_row:
            level = access_row[0]
            result["can_write"] = level in ("USER_WRITE", "USER_ADMIN")
            result["can_admin"] = level == "USER_ADMIN"
        else:
            # Public/unlisted can view, but not write/admin
            result["can_write"] = False
            result["can_admin"] = False

    result["graph_projection"] = projection

    warnings = await _get_contract_warnings(db, row)
    result["contract_warnings"] = warnings

    # Artifact counts
    cursor = await db.execute(
        "SELECT COUNT(*) FROM artifacts WHERE node_id = ?", (node_id,)
    )
    result["artifacts_total"] = (await cursor.fetchone())[0]
    result["artifacts_truncated"] = False

    # Full projection includes uploaded artifacts. Managed executions were
    # retired; clients run local or user-owned compute independently.
    if projection == "full":
        from atlas_graph.services.artifact_service import list_artifacts as _list_artifacts

        result["artifacts"] = await _list_artifacts(db, user_id, node_id)

    return result


# ---------------------------------------------------------------------------
# list_nodes
# ---------------------------------------------------------------------------

def _root_access_exists_sql(root_predicate: str) -> str:
    """SQL predicate: any graph root containing ``n`` satisfies predicate.

    Graph membership is derived from the DAG at read time. A node may be
    reachable from multiple roots; access through any root is sufficient.
    ``root_predicate`` is written against alias ``r``.
    """
    return f"""
    EXISTS (
      WITH RECURSIVE ancestors(current_id) AS (
        SELECT n.node_id
        UNION
        SELECT e.parent_id
        FROM node_edges e
        JOIN ancestors a ON e.child_id = a.current_id
      )
      SELECT 1
      FROM nodes r
      WHERE r.node_id IN (
        SELECT current_id FROM ancestors
        WHERE current_id NOT IN (SELECT child_id FROM node_edges)
      )
      AND ({root_predicate})
      LIMIT 1
    )
    """


async def list_nodes(
    db,
    user_id: str,
    scope: str | None = None,
    owners: list[str] | None = None,
    writers: list[str] | None = None,
    visibility: str | None = None,
    kind: str | None = None,
    lifecycle: str | None = None,
    outcome: str | None = None,
    root_only: bool | None = None,
    require_children: bool | None = None,
    repo_url: str | None = None,
    tag_id: str | None = None,
    title: str | None = None,
    projection: str = "core",
    page: int = 1,
    per_page: int = 50,
) -> dict:
    """List nodes with filters and pagination.

    Access control: only returns nodes the user owns, has access rules for,
    or are public/unlisted.  The ``visibility`` filter maps to:

    - ``"my_nodes"``        -- owned by user
    - ``"shared_with_me"``  -- has access rule but not owner
    - ``"public"``          -- sharing_mode = public
    """
    conditions: list[str] = []
    params: list[Any] = []

    # --- Access-control gate (always applied) ---
    # Visibility is graph-scoped: roots carry sharing_mode/collaborators, every
    # descendant inherits, so a descendant's access is checked against its
    # root via a recursive CTE.
    #
    # BUT for root_only queries every result is itself a root, and a root's
    # root is itself -- so the recursive root-access check is exactly the
    # node's own columns. We use index-friendly direct predicates there. This
    # is the hot path (Explore feed + dashboard, both root_only=true) and the
    # per-row recursive CTE was holding pool connections long enough under
    # load to saturate the pool. Access semantics are identical for roots.
    _shared_n = (
        "EXISTS (SELECT 1 FROM node_access_rules ar WHERE ar.node_id = n.node_id AND ar.user_id = ?)"
    )
    public_enabled = bool(config.PUBLIC_GRAPHS_ENABLED)
    if scope not in (None, "owned_or_shared_private"):
        raise ValueError("unsupported node-list scope")
    if scope and visibility is not None:
        raise ValueError("scope and visibility are mutually exclusive")
    if root_only:
        if scope == "owned_or_shared_private":
            conditions.append(f"(n.owner_user_id = ? OR {_shared_n})")
            params.extend([user_id, user_id])
        elif visibility == "my_nodes":
            conditions.append("n.owner_user_id = ?")
            params.append(user_id)
        elif visibility == "shared_with_me":
            conditions.append(f"(n.owner_user_id != ? AND {_shared_n})")
            params.extend([user_id, user_id])
        elif visibility == "public":
            conditions.append("n.sharing_mode = 'public'" if public_enabled else "1 = 0")
        elif visibility == "unlisted":
            conditions.append("n.sharing_mode = 'unlisted'" if public_enabled else "1 = 0")
        elif visibility == "private":
            conditions.append("(n.owner_user_id = ? AND n.sharing_mode = 'private')")
            params.append(user_id)
        else:
            public_clause = "n.sharing_mode IN ('public', 'unlisted') OR " if public_enabled else ""
            conditions.append(f"(n.owner_user_id = ? OR {public_clause}{_shared_n})")
            params.extend([user_id, user_id])
    else:
        root_owner_sql = _root_access_exists_sql("r.owner_user_id = ?")
        root_public_sql = _root_access_exists_sql("r.sharing_mode = 'public'")
        root_unlisted_sql = _root_access_exists_sql("r.sharing_mode = 'unlisted'")
        root_private_sql = _root_access_exists_sql("r.owner_user_id = ? AND r.sharing_mode = 'private'")
        root_shared_sql = _root_access_exists_sql(
            "r.owner_user_id != ? AND EXISTS (SELECT 1 FROM node_access_rules ar2 WHERE ar2.node_id = r.node_id AND ar2.user_id = ?)"
        )
        root_visible_sql = _root_access_exists_sql(
            "r.owner_user_id = ? OR r.sharing_mode IN ('public', 'unlisted') OR EXISTS (SELECT 1 FROM node_access_rules ar2 WHERE ar2.node_id = r.node_id AND ar2.user_id = ?)"
        )
        if scope == "owned_or_shared_private":
            root_owned_or_shared = _root_access_exists_sql(
                "r.owner_user_id = ? OR EXISTS (SELECT 1 FROM node_access_rules ar2 WHERE ar2.node_id = r.node_id AND ar2.user_id = ?)"
            )
            conditions.append(
                f"(n.owner_user_id = ? OR {_shared_n} OR {root_owned_or_shared})"
            )
            params.extend([user_id, user_id, user_id, user_id])
        elif visibility == "my_nodes":
            conditions.append(f"(n.owner_user_id = ? OR {root_owner_sql})")
            params.extend([user_id, user_id])
        elif visibility == "shared_with_me":
            conditions.append(
                f"(n.owner_user_id != ? AND ({_shared_n} OR {root_shared_sql}))"
            )
            params.extend([user_id, user_id, user_id, user_id])
        elif visibility == "public":
            conditions.append(f"(n.sharing_mode = 'public' OR {root_public_sql})" if public_enabled else "1 = 0")
        elif visibility == "unlisted":
            conditions.append(f"(n.sharing_mode = 'unlisted' OR {root_unlisted_sql})" if public_enabled else "1 = 0")
        elif visibility == "private":
            conditions.append(
                f"(n.owner_user_id = ? AND (n.sharing_mode = 'private' OR {root_private_sql}))"
            )
            params.extend([user_id, user_id])
        else:
            if public_enabled:
                conditions.append(
                    f"(n.owner_user_id = ? OR n.sharing_mode IN ('public', 'unlisted') OR {_shared_n} OR {root_visible_sql})"
                )
                params.extend([user_id, user_id, user_id, user_id])
            else:
                root_owned_or_shared = _root_access_exists_sql(
                    "r.owner_user_id = ? OR EXISTS (SELECT 1 FROM node_access_rules ar2 WHERE ar2.node_id = r.node_id AND ar2.user_id = ?)"
                )
                conditions.append(
                    f"(n.owner_user_id = ? OR {_shared_n} OR {root_owned_or_shared})"
                )
                params.extend([user_id, user_id, user_id, user_id])

    if owners:
        resolved = [user_id if o == "me" else o for o in owners]
        placeholders = ",".join("?" for _ in resolved)
        conditions.append(f"n.owner_user_id IN ({placeholders})")
        params.extend(resolved)

    if kind:
        conditions.append("n.node_type = ?")
        params.append(kind)

    if lifecycle:
        conditions.append("n.lifecycle = ?")
        params.append(lifecycle)

    if outcome:
        conditions.append("n.outcome = ?")
        params.append(outcome)

    if repo_url:
        conditions.append("n.repo_url = ?")
        params.append(repo_url)

    if title:
        conditions.append("n.title LIKE ?")
        params.append(f"%{title}%")

    if root_only:
        conditions.append(
            "NOT EXISTS (SELECT 1 FROM node_edges e WHERE e.child_id = n.node_id)"
        )

    if require_children:
        # Only "real" multi-node graphs -- the root must have at least one
        # child. Used by public Explore so standalone public nodes (single-node
        # graphs) are not surfaced as discoverable graphs.
        conditions.append(
            "EXISTS (SELECT 1 FROM node_edges e2 WHERE e2.parent_id = n.node_id)"
        )

    # Tag-based filtering: join through tag_assignments
    join_clause = ""
    if tag_id:
        join_clause = " JOIN tag_assignments ta ON ta.node_id = n.node_id"
        conditions.append("ta.tag_id = ?")
        params.append(tag_id)

    where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""

    # Count total
    count_sql = f"SELECT COUNT(DISTINCT n.node_id) FROM nodes n{join_clause}{where_clause}"
    cursor = await db.execute(count_sql, params)
    total = (await cursor.fetchone())[0]

    # Fetch page
    offset = (page - 1) * per_page
    query_sql = (
        f"SELECT DISTINCT n.* FROM nodes n{join_clause}{where_clause} "
        f"ORDER BY n.updated_at DESC LIMIT ? OFFSET ?"
    )
    cursor = await db.execute(query_sql, params + [per_page, offset])
    columns = [desc[0] for desc in cursor.description]
    rows = [dict(zip(columns, r)) for r in await cursor.fetchall()]

    # Batch-fetch all edges in one query instead of N+1
    node_ids = [row["node_id"] for row in rows]
    parents_map, children_map = await edge_repo.get_edges_for_nodes(db, node_ids)

    nodes = []
    for row in rows:
        nid = row["node_id"]
        parent_ids = parents_map.get(nid, [])
        child_ids = children_map.get(nid, [])
        node_dict = _build_node_response(row, parent_ids, child_ids)
        node_dict["graph_projection"] = projection
        nodes.append(node_dict)

    has_more = (offset + per_page) < total

    return {
        "nodes": nodes,
        "total": total,
        "page": page,
        "per_page": per_page,
        "has_more": has_more,
    }


# ---------------------------------------------------------------------------
# get_graph / direct relation pagination
# ---------------------------------------------------------------------------

def _normalize_token_list(value: list[str] | str | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return [str(item).strip() for item in value if str(item).strip()]


async def list_node_relations(
    db,
    user_id: str,
    node_id: str,
    *,
    direction: str,
    first: int = 100,
    after: str | None = None,
    projection: str = "topology",
) -> dict:
    """Page direct visible parents or children for one node."""
    await require_node_access(db, user_id, node_id, "view")
    first = max(1, min(int(first or 100), 500))
    offset = _parse_cursor(after)

    if direction == "children":
        related_ids = await edge_repo.get_children(db, node_id)
        edge_key = "child"
    elif direction == "parents":
        related_ids = await edge_repo.get_parents(db, node_id)
        edge_key = "parent"
    else:
        raise ValueError("direction must be 'children' or 'parents'")

    visible_ids: list[str] = []
    for related_id in related_ids:
        if await check_node_access(db, user_id, related_id, "view"):
            visible_ids.append(related_id)

    page_ids = visible_ids[offset: offset + first]
    nodes = [
        await get_node(db, user_id, related_id, projection=projection)
        for related_id in page_ids
    ]
    edges = [
        {
            "parent_id": node_id if direction == "children" else related_id,
            "child_id": related_id if direction == "children" else node_id,
            edge_key: node,
            "node": node,
        }
        for related_id, node in zip(page_ids, nodes)
    ]
    return {
        "node_id": node_id,
        "direction": direction,
        "edges": edges,
        "nodes": nodes,
        "page_info": _page_info(offset, first, len(visible_ids)),
        "total_count": len(visible_ids),
    }


async def get_graph(
    db,
    user_id: str,
    *,
    node_id: str | None = None,
    depth: int | None = None,
    max_nodes: int | None = None,
    page_size: int = 500,
    cursor: str | None = None,
    filters: list[str] | str | None = None,
    exclude: list[str] | str | None = None,
) -> dict:
    """Return a navigation-friendly graph projection.

    The filter tokens are accepted for CLI compatibility. This focused
    backend implementation applies access control and supports root scoping,
    depth limiting, max node limits, and cursor pagination.
    """
    _normalize_token_list(filters)
    _normalize_token_list(exclude)
    page_size = max(1, min(int(page_size or 500), 10_000))
    offset = _parse_cursor(cursor)
    projection = "topology"

    if node_id:
        tree = await get_node_tree(
            db,
            user_id,
            node_id,
            projection=projection,
            max_nodes=max_nodes or 5000,
            max_depth=depth,
        )
        all_nodes = tree["nodes"]
    else:
        listed = await list_nodes(
            db,
            user_id,
            projection=projection,
            page=1,
            per_page=max_nodes or max(page_size + offset, page_size),
        )
        all_nodes = listed["nodes"]

    total = len(all_nodes)
    page_nodes = all_nodes[offset: offset + page_size]
    page_node_ids = {node["node_id"] for node in page_nodes}
    edges: list[dict[str, str]] = []
    for node in page_nodes:
        child_ids = node.get("child_ids") or []
        for child_id in child_ids:
            if child_id in page_node_ids:
                edges.append({"parent_id": node["node_id"], "child_id": child_id})

    return {
        "nodes": page_nodes,
        "edges": edges,
        "node_count": len(page_nodes),
        "total_count": total,
        "page_info": _page_info(offset, page_size, total),
        "root_node_ids": [
            node["node_id"] for node in page_nodes if not node.get("parent_ids")
        ],
    }


# ---------------------------------------------------------------------------
# get_node_tree
# ---------------------------------------------------------------------------

async def get_node_tree(
    db,
    user_id: str,
    node_id: str,
    projection: str = "core",
    max_nodes: int = 5000,
    max_depth: int | None = None,
) -> dict:
    """
    Return the full tree (up and down) from a given anchor node,
    up to max_nodes.
    """
    await require_node_access(db, user_id, node_id, "view")

    if max_depth is None:
        # get_connected_component is bidirectional, so the component seeded from
        # the anchor is identical to the one seeded from the root -- skip the
        # redundant find_root_node_id ancestor walk on this hot path.
        node_rows = await node_repo.get_connected_component(
            db,
            node_id,
            max_nodes=max_nodes,
        )
    else:
        if max_depth < 0:
            raise ValueError("max_depth must be >= 0")
        # The depth-limited walk is anchored at the root, so resolve it here.
        root_id = await node_repo.find_root_node_id(db, node_id) or node_id
        node_rows = await node_repo.get_node_tree_to_depth(
            db,
            root_id,
            max_depth=max_depth,
            max_nodes=max_nodes,
        )

    # Batch-fetch all edges in one query instead of N+1
    tree_node_ids = [row["node_id"] for row in node_rows]
    parents_map, children_map = await edge_repo.get_edges_for_nodes(db, tree_node_ids)

    # Find root node IDs (nodes with no parents in the visited set)
    root_ids: list[str] = []
    nodes = []
    for row in node_rows:
        nid = row["node_id"]
        parent_ids = parents_map.get(nid, [])
        child_ids = children_map.get(nid, [])
        node_dict = _build_node_response(row, parent_ids, child_ids)
        node_dict["graph_projection"] = projection
        nodes.append(node_dict)

        # A root is a node with no parents
        if not parent_ids:
            root_ids.append(nid)

    return {
        "anchor_node_id": node_id,
        "root_node_ids": root_ids,
        "nodes": nodes,
        "node_count": len(nodes),
    }


_PAPER_URL_KEYS = ("paper_url", "arxiv_url", "source_url", "pdf_url", "doi_url")


def _derive_paper_url(semantic: dict | None) -> str | None:
    """Best-effort paper link for a graph card, from root semantic_data."""
    if not isinstance(semantic, dict):
        return None
    for key in _PAPER_URL_KEYS:
        value = semantic.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    return None


_AUTORESEARCH_MARKERS = ("optimize_run", "autoresearch", "campaign", "auto_run")


def _is_autoresearch(semantic: dict | None) -> bool:
    if not isinstance(semantic, dict):
        return False
    t = semantic.get("type")
    if isinstance(t, str) and t in _AUTORESEARCH_MARKERS:
        return True
    # control nodes / optimize runs / campaigns carry these keys
    return any(k in semantic for k in ("optimize_run", "campaign_id", "stop_reason", "budget_total"))


def _graph_category(semantic: dict | None, paper_url: str | None) -> str:
    if paper_url:
        return "paper"
    if _is_autoresearch(semantic):
        return "autoresearch"
    return "graph"


def _require_public_surface() -> None:
    if not config.PUBLIC_GRAPHS_ENABLED:
        raise ValueError("Public graph not found")


async def explore_public_graph_cards(
    db,
    *,
    user_id: str | None = None,
    owner_user_id: str | None = None,
    title: str | None = None,
    has_paper: bool | None = None,
    has_code: bool | None = None,
    forked: bool | None = None,
    autoresearch: bool | None = None,
    sort: str = "trending",
    page: int = 1,
    per_page: int = 24,
    candidate_cap: int = 500,
) -> dict:
    """Enriched, public archive of whole graphs (GitHub x arXiv style).

    Only project roots with at least one child are surfaced (never bare
    nodes). Each card carries author, full graph size, stars, forks, paper
    link, and code presence. Trending/Top/Forks sorts are computed over the
    candidate set (capped) so ranking is global, not page-local.
    """
    _require_public_surface()
    from atlas_graph.db.repos import graph_social_repo

    clauses = [
        "n.sharing_mode = 'public'",
        "NOT EXISTS (SELECT 1 FROM node_edges e WHERE e.child_id = n.node_id)",
        "EXISTS (SELECT 1 FROM node_edges e2 WHERE e2.parent_id = n.node_id)",
    ]
    params: list[Any] = []
    if owner_user_id:
        clauses.append("n.owner_user_id = ?")
        params.append(owner_user_id)
    if autoresearch is True:
        clauses.append(
            "("
            + " OR ".join(
                f"CAST(n.semantic_data AS TEXT) LIKE '%\"{m}\"%'"
                for m in _AUTORESEARCH_MARKERS
            )
            + ")"
        )
    if title:
        q = f"%{title.strip().lower()}%"
        clauses.append(
            """(
                LOWER(COALESCE(n.title, '')) LIKE ?
                OR LOWER(COALESCE(n.summary, '')) LIKE ?
                OR LOWER(COALESCE(n.slug_name, '')) LIKE ?
                OR EXISTS (
                    SELECT 1 FROM users u
                    WHERE u.user_id = n.owner_user_id
                      AND (
                        LOWER(COALESCE(u.github_username, '')) LIKE ?
                        OR LOWER(COALESCE(u.display_name, '')) LIKE ?
                        OR LOWER(COALESCE(u.email, '')) LIKE ?
                      )
                )
            )"""
        )
        params.extend([q, q, q, q, q, q])
    if has_code is True:
        clauses.append("n.repo_url IS NOT NULL AND n.repo_url != ''")
    elif has_code is False:
        clauses.append("(n.repo_url IS NULL OR n.repo_url = '')")
    if has_paper is True:
        clauses.append(
            "("
            + " OR ".join(
                f"CAST(n.semantic_data AS TEXT) LIKE '%\"{key}\"%'"
                for key in _PAPER_URL_KEYS
            )
            + ")"
        )
    elif has_paper is False:
        clauses.append(
            "NOT ("
            + " OR ".join(
                f"COALESCE(CAST(n.semantic_data AS TEXT), '') LIKE '%\"{key}\"%'"
                for key in _PAPER_URL_KEYS
            )
            + ")"
        )
    if forked is True:
        clauses.append("CAST(n.semantic_data AS TEXT) LIKE '%\"forked_from\"%'")
    elif forked is False:
        clauses.append("COALESCE(CAST(n.semantic_data AS TEXT), '') NOT LIKE '%\"forked_from\"%'")
    where = " AND ".join(clauses)
    cursor = await db.execute(
        f"""
        SELECT n.node_id, n.slug_name, n.title, n.summary, n.owner_user_id,
               n.repo_url, n.head_commit_sha, n.branch_name, n.node_type,
               n.lifecycle, n.semantic_data, n.created_at, n.updated_at
        FROM nodes n
        WHERE {where}
        ORDER BY n.updated_at DESC
        LIMIT ?
        """,
        (*params, candidate_cap),
    )
    cols = [d[0] for d in cursor.description]
    rows = [dict(zip(cols, r)) for r in await cursor.fetchall()]

    root_ids = [r["node_id"] for r in rows]
    stars = await graph_social_repo.star_counts(db, root_ids)
    forks = await graph_social_repo.fork_counts(db, root_ids)
    starred = await graph_social_repo.starred_set(db, root_ids, user_id)

    def _recency(r: dict) -> str:
        return str(r.get("updated_at") or r.get("created_at") or "")

    def sort_key(r: dict):
        rid = r["node_id"]
        s, f = stars.get(rid, 0), forks.get(rid, 0)
        if sort in ("top", "stars"):
            return (s, f, _recency(r))
        if sort in ("forks", "forked"):
            return (f, s, _recency(r))
        if sort in ("new", "newest"):
            return (str(r.get("created_at") or ""),)
        if sort == "trending":
            return (s * 2 + f * 3, _recency(r))
        return (_recency(r),)  # "recent" / default

    rows.sort(key=sort_key, reverse=True)

    total = len(rows)
    offset = (page - 1) * per_page
    page_rows = rows[offset: offset + per_page]

    owner_ids = list({r["owner_user_id"] for r in page_rows if r.get("owner_user_id")})
    authors: dict[str, dict] = {}
    if owner_ids:
        ph = ",".join("?" for _ in owner_ids)
        ac = await db.execute(
            f"SELECT user_id, github_username, display_name, email, avatar_url "
            f"FROM users WHERE user_id IN ({ph})",
            tuple(owner_ids),
        )
        for u in await ac.fetchall():
            d = dict(u)
            authors[d["user_id"]] = d

    # Descendant counts for the whole page in ONE recursive CTE (was a per-card
    # N+1 — one recursive CTE per card, which scaled badly with page size).
    descendant_counts = await node_repo.count_descendants_batch(
        db, [r["node_id"] for r in page_rows]
    )

    cards = []
    page_paper_count = 0
    page_code_count = 0
    page_forked_count = 0
    for r in page_rows:
        rid = r["node_id"]
        semantic = parse_node_semantics(r)
        owner = authors.get(r.get("owner_user_id") or "", {})
        handle = (
            owner.get("github_username")
            or owner.get("display_name")
            or (owner.get("email") or "").split("@")[0]
            or "anonymous"
        )
        forked_from = semantic.get("forked_from") if isinstance(semantic, dict) else None
        paper_url = _derive_paper_url(semantic)
        has_code_value = bool(r.get("repo_url"))
        if paper_url:
            page_paper_count += 1
        if has_code_value:
            page_code_count += 1
        if isinstance(forked_from, dict):
            page_forked_count += 1
        cards.append({
            "node_id": rid,
            "slug_name": r.get("slug_name"),
            "title": r.get("title") or "untitled",
            "summary": r.get("summary") or "",
            "kind": r.get("node_type", "untyped"),
            "lifecycle": r.get("lifecycle"),
            "author": {
                "handle": handle,
                "github_username": owner.get("github_username"),
                "avatar_url": owner.get("avatar_url"),
            },
            "node_count": descendant_counts.get(rid, 0),
            "star_count": stars.get(rid, 0),
            "fork_count": forks.get(rid, 0),
            "viewer_has_starred": rid in starred,
            "has_code": has_code_value,
            "repo_url": r.get("repo_url"),
            "paper_url": paper_url,
            "category": _graph_category(semantic, paper_url),
            "forked_from": forked_from if isinstance(forked_from, dict) else None,
            "created_at": r.get("created_at"),
            "updated_at": r.get("updated_at"),
        })

    return {
        "graphs": cards,
        "total": total,
        "page": page,
        "per_page": per_page,
        "has_more": offset + per_page < total,
        "sort": sort,
        "facets": {
            "stars_on_page": sum(stars.get(r["node_id"], 0) for r in page_rows),
            "forks_on_page": sum(forks.get(r["node_id"], 0) for r in page_rows),
            "papers_on_page": page_paper_count,
            "code_on_page": page_code_count,
            "forked_on_page": page_forked_count,
        },
    }


_PUBLIC_GRAPH_PREDICATE = (
    "n.sharing_mode = 'public' "
    "AND NOT EXISTS (SELECT 1 FROM node_edges e WHERE e.child_id = n.node_id) "
    "AND EXISTS (SELECT 1 FROM node_edges e2 WHERE e2.parent_id = n.node_id)"
)


async def count_public_graphs_for_owner(db, owner_user_id: str) -> int:
    _require_public_surface()
    cursor = await db.execute(
        f"SELECT COUNT(*) FROM nodes n WHERE n.owner_user_id = ? AND {_PUBLIC_GRAPH_PREDICATE}",
        (owner_user_id,),
    )
    row = await cursor.fetchone()
    return int(row[0]) if row else 0


def public_profile_shape(row: dict | None, public_graph_count: int) -> dict:
    """Public-safe profile (no email / internal ids leaked)."""
    row = row or {}
    handle = (
        row.get("github_username")
        or row.get("display_name")
        or (row.get("email") or "").split("@")[0]
        or "anonymous"
    )
    return {
        "handle": handle,
        "github_username": row.get("github_username"),
        "display_name": row.get("display_name") or row.get("full_name"),
        "avatar_url": row.get("avatar_url"),
        "created_at": row.get("created_at"),
        "public_graph_count": public_graph_count,
    }


async def list_public_researchers(
    db, *, q: str | None = None, sort: str = "graphs", page: int = 1, per_page: int = 24
) -> dict:
    """Searchable directory of users who have published a public graph.

    A profile is only discoverable if the user has **at least one public
    graph** (the JOIN enforces this), so non-contributing accounts can't be
    scraped out. Discovery is search-driven: an empty query returns nothing
    rather than enumerating every researcher.
    """
    _require_public_surface()
    needle = (q or "").strip().lower()
    if not needle:
        return {
            "researchers": [],
            "total": 0,
            "page": page,
            "per_page": per_page,
            "has_more": False,
        }

    like = f"%{needle}%"
    cursor = await db.execute(
        f"""
        SELECT u.user_id, u.github_username, u.display_name, u.full_name,
               u.avatar_url, u.email, u.created_at,
               COUNT(n.node_id) AS public_graph_count
        FROM users u
        JOIN nodes n ON n.owner_user_id = u.user_id AND {_PUBLIC_GRAPH_PREDICATE}
        WHERE u.github_username IS NOT NULL AND u.github_username != ''
          AND (LOWER(u.github_username) LIKE ?
               OR LOWER(COALESCE(u.display_name, '')) LIKE ?
               OR LOWER(COALESCE(u.full_name, '')) LIKE ?)
        GROUP BY u.user_id, u.github_username, u.display_name, u.full_name,
                 u.avatar_url, u.email, u.created_at
        ORDER BY public_graph_count DESC
        """,
        (like, like, like),
    )
    cols = [d[0] for d in cursor.description]
    rows = [dict(zip(cols, r)) for r in await cursor.fetchall()]

    if sort == "new":
        rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    else:  # "graphs"
        rows.sort(key=lambda r: int(r.get("public_graph_count") or 0), reverse=True)

    total = len(rows)
    offset = (page - 1) * per_page
    page_rows = rows[offset: offset + per_page]
    researchers = [
        public_profile_shape(r, int(r.get("public_graph_count") or 0)) for r in page_rows
    ]
    return {
        "researchers": researchers,
        "total": total,
        "page": page,
        "per_page": per_page,
        "has_more": offset + per_page < total,
    }


async def set_graph_star(db, user_id: str, node_id: str, *, starred: bool) -> dict:
    """Star/unstar the graph containing ``node_id`` (resolves to its root)."""
    from atlas_graph.db.repos import graph_social_repo

    await require_node_access(db, user_id, node_id, "view")
    root_id = await node_repo.find_root_node_id(db, node_id) or node_id
    if starred:
        await graph_social_repo.add_star(db, root_node_id=root_id, user_id=user_id)
    else:
        await graph_social_repo.remove_star(db, root_node_id=root_id, user_id=user_id)
    return {
        "root_node_id": root_id,
        "star_count": await graph_social_repo.star_count(db, root_id),
        "viewer_has_starred": starred,
    }


async def public_graph_social(db, node_id: str, user_id: str | None) -> dict:
    _require_public_surface()
    """Star/fork signals for a public graph (or one the viewer can access)."""
    from atlas_graph.db.repos import graph_social_repo

    node_id = await _resolve_public_node_ref(db, node_id)
    root_id = await node_repo.find_root_node_id(db, node_id) or node_id
    root_row = await node_repo.get_node(db, root_id)
    if root_row is None:
        raise ValueError("Public graph not found")
    if (root_row.get("sharing_mode") or "private") != "public":
        if not await check_node_access(db, user_id or "__anonymous__", root_id, "view"):
            raise ValueError("Public graph not found")
    return {
        "root_node_id": root_id,
        "star_count": await graph_social_repo.star_count(db, root_id),
        "fork_count": (await graph_social_repo.fork_counts(db, [root_id])).get(root_id, 0),
        "viewer_has_starred": await graph_social_repo.has_starred(db, root_id, user_id),
    }


def _artifact_size(metadata: dict | None) -> int | None:
    if not isinstance(metadata, dict):
        return None
    for key in ("size", "bytes", "size_bytes", "content_length"):
        value = metadata.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return int(value)
    return None


async def public_node_artifacts(db, node_id: str, user_id: str | None) -> dict:
    _require_public_surface()
    """Read-only artifact/evidence list for a node inside a public graph.

    View-gated by the same rule as the rest of the public surface, so a node
    whose root is not public (and that the caller can't otherwise see) returns
    "not found" rather than leaking its existence. Download links point at the
    public, view-gated download route below.
    """
    node_id = await _resolve_public_node_ref(db, node_id)
    viewer = user_id or "__anonymous__"
    if not await check_node_access(db, viewer, node_id, "view"):
        raise ValueError("Public graph not found")

    cursor = await db.execute(
        "SELECT * FROM artifacts WHERE node_id = ? ORDER BY created_at",
        (node_id,),
    )
    columns = [desc[0] for desc in cursor.description]
    rows = [dict(zip(columns, r)) for r in await cursor.fetchall()]

    items = []
    for row in rows:
        metadata = row.get("metadata", "{}")
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except (json.JSONDecodeError, TypeError):
                metadata = {}
        payload = row.get("payload", "{}")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (json.JSONDecodeError, TypeError):
                payload = {}
        storage_path = row.get("storage_path") or ""
        title = row.get("title") or (storage_path.rsplit("/", 1)[-1] if storage_path else "") or "artifact"
        external_url = payload.get("url") if isinstance(payload, dict) else None
        items.append({
            "artifact_id": row["artifact_id"],
            "title": title,
            "artifact_type": row.get("artifact_type"),
            "media_type": metadata.get("media_type") if isinstance(metadata, dict) else None,
            "size": _artifact_size(metadata),
            "note": row.get("note"),
            "created_at": row.get("created_at", ""),
            "external_url": external_url if isinstance(external_url, str) else None,
            "download_url": f"/nodes/explore/{node_id}/artifacts/{row['artifact_id']}/download",
        })
    return {"node_id": node_id, "artifacts": items}


async def resolve_public_artifact_blob(
    db, node_id: str, artifact_id: str, user_id: str | None
) -> dict:
    _require_public_surface()
    """Resolve a public artifact to a redirect URL or raw bytes for download.

    Reuses the public view-gate. Prefers a signed/remote https URL (302) and
    falls back to streaming the stored blob (local dev / proxied storage).
    """
    node_id = await _resolve_public_node_ref(db, node_id)
    viewer = user_id or "__anonymous__"
    if not await check_node_access(db, viewer, node_id, "view"):
        raise ValueError("artifact not found")

    cursor = await db.execute(
        "SELECT * FROM artifacts WHERE node_id = ? AND artifact_id = ?",
        (node_id, artifact_id),
    )
    columns = [desc[0] for desc in cursor.description]
    raw = await cursor.fetchone()
    if raw is None:
        raise ValueError("artifact not found")
    row = dict(zip(columns, raw))

    # 1) An absolute https URL already on the row (signed Supabase URL).
    storage_url = row.get("storage_url")
    if isinstance(storage_url, str) and storage_url.startswith(("http://", "https://")):
        return {"redirect": storage_url}

    # 2) Remote-linked evidence carries its URL in the payload.
    payload = row.get("payload", "{}")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            payload = {}
    external = payload.get("url") if isinstance(payload, dict) else None
    if isinstance(external, str) and external.startswith(("http://", "https://")):
        return {"redirect": external}

    # 3) A stored blob (relative storage_path) — stream the bytes.
    storage_path = row.get("storage_path") or ""
    if not storage_path:
        raise ValueError("artifact not found")
    from atlas_graph.storage.supabase_storage import storage as _storage
    import mimetypes

    data = await _storage.download(storage_path)
    metadata = row.get("metadata", "{}")
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except (json.JSONDecodeError, TypeError):
            metadata = {}
    media_type = (
        (metadata.get("media_type") if isinstance(metadata, dict) else None)
        or mimetypes.guess_type(storage_path)[0]
        or "application/octet-stream"
    )
    filename = row.get("title") or storage_path.rsplit("/", 1)[-1]
    return {"bytes": data, "media_type": media_type, "filename": filename}


async def _resolve_public_node_ref(db, node_id: str) -> str:
    """Resolve a public ``{node_id}`` path param that may be a human slug.

    Public explore URLs carry the slug (e.g. ``bold-haze-0391``), not the uuid.
    On Postgres ``nodes.node_id`` is a uuid column, so querying it with a slug
    raises (``invalid input syntax for type uuid``) and surfaces as a 500.
    Resolve the slug to its canonical uuid first; pass uuids through untouched.
    Raises ``ValueError("Public graph not found")`` when a non-uuid slug has no
    match so callers turn it into a clean 404.
    """
    ref = str(node_id)
    try:
        uuid.UUID(ref)
        return ref  # already a canonical uuid - no lookup needed
    except (ValueError, TypeError, AttributeError):
        pass
    cursor = await db.execute(
        "SELECT node_id FROM nodes WHERE slug_name = ? LIMIT 1", (ref,)
    )
    row = await cursor.fetchone()
    if not row:
        raise ValueError("Public graph not found")
    return dict(row)["node_id"]


async def get_public_root_tree(
    db,
    node_id: str,
    projection: str = "topology",
    max_nodes: int = 5000,
) -> dict:
    _require_public_surface()
    """Return a read-only public graph rooted at ``node_id``.

    Public browsing treats the root node as the graph/paper boundary.  Once a
    root has been shared publicly, its descendants are rendered inside that
    graph even when individual child nodes are not independently public.
    """
    node_id = await _resolve_public_node_ref(db, node_id)
    root_row = await node_repo.get_node(db, node_id)
    if root_row is None or (root_row.get("sharing_mode") or "private") != "public":
        raise ValueError("Public graph not found")

    root_parents = await edge_repo.get_parents(db, node_id)
    if root_parents:
        raise ValueError("Public graph not found")

    max_nodes = max(1, min(int(max_nodes or 5000), 10000))
    # A public graph is the root plus its descendant subtree. Fetch the whole
    # subtree in one recursive CTE instead of a per-node Python BFS (which was
    # 2N+1 serialized queries -- get_node + get_children per node).
    node_rows = await node_repo.get_node_tree(db, node_id, max_nodes=max_nodes)

    tree_node_ids = [row["node_id"] for row in node_rows]
    tree_node_id_set = set(tree_node_ids)
    parents_map, children_map = await edge_repo.get_edges_for_nodes(db, tree_node_ids)

    nodes = []
    for row in node_rows:
        nid = row["node_id"]
        parent_ids = [
            parent_id
            for parent_id in parents_map.get(nid, [])
            if parent_id in tree_node_id_set
        ]
        child_ids = [
            child_id
            for child_id in children_map.get(nid, [])
            if child_id in tree_node_id_set
        ]
        node_dict = _build_node_response(row, parent_ids, child_ids)
        node_dict["graph_projection"] = projection
        node_dict["is_owner"] = False
        node_dict["can_write"] = False
        node_dict["can_admin"] = False
        node_dict["visibility"] = (
            "public" if nid == node_id else row.get("sharing_mode", "private")
        )
        nodes.append(node_dict)

    return {
        "anchor_node_id": node_id,
        "root_node_ids": [node_id],
        "nodes": nodes,
        "node_count": len(nodes),
    }


# ---------------------------------------------------------------------------
# get_node_ancestry
# ---------------------------------------------------------------------------

async def get_node_ancestry(
    db,
    user_id: str,
    node_id: str,
    projection: str = "core",
    max_depth: int = 256,
) -> list[dict]:
    """Return the ancestry chain from node_id up to roots, max_depth levels."""
    await require_node_access(db, user_id, node_id, "view")

    # Phase 1: BFS traversal to collect ancestor node rows
    visited: set[str] = set()
    node_rows: list[dict] = []
    queue = [node_id]
    depth = 0

    while queue and depth < max_depth:
        next_queue: list[str] = []
        for nid in queue:
            if nid in visited:
                continue
            visited.add(nid)

            row = await node_repo.get_node(db, nid)
            if row is None:
                continue
            node_rows.append(row)

            parent_ids = await edge_repo.get_parents(db, nid)
            for pid in parent_ids:
                if pid not in visited:
                    next_queue.append(pid)

        queue = next_queue
        depth += 1

    # Phase 2: Batch-fetch all edges in one query for response assembly
    ancestry_node_ids = [row["node_id"] for row in node_rows]
    parents_map, children_map = await edge_repo.get_edges_for_nodes(db, ancestry_node_ids)

    result: list[dict] = []
    for row in node_rows:
        nid = row["node_id"]
        parent_ids = parents_map.get(nid, [])
        child_ids = children_map.get(nid, [])
        node_dict = _build_node_response(row, parent_ids, child_ids)
        node_dict["graph_projection"] = projection
        result.append(node_dict)

    return result


# ---------------------------------------------------------------------------
# resolve_node_slug
# ---------------------------------------------------------------------------

async def resolve_node_slug(
    db,
    user_id: str,
    slug_name: str,
    context_node_id: str | None = None,
) -> dict:
    """
    Resolve a slug to a node.  Returns a dict with node_id, slug_name,
    title, and the full node object.
    """
    cursor = await db.execute(
        "SELECT * FROM nodes WHERE slug_name = ? LIMIT 1", (slug_name,)
    )
    columns = [desc[0] for desc in cursor.description]
    raw = await cursor.fetchone()
    if raw is None:
        return {
            "resolved": False,
            "slug_name": slug_name,
            "node_id": None,
            "node": None,
        }

    row = dict(zip(columns, raw))
    nid = row["node_id"]

    # Check view access -- if denied, treat as not found
    if not await check_node_access(db, user_id, nid, "view"):
        return {
            "resolved": False,
            "slug_name": slug_name,
            "node_id": None,
            "node": None,
        }

    parent_ids = await edge_repo.get_parents(db, nid)
    child_ids = await edge_repo.get_children(db, nid)
    node_dict = _build_node_response(row, parent_ids, child_ids)

    return {
        "resolved": True,
        "slug_name": slug_name,
        "node_id": nid,
        "node": node_dict,
    }


# ---------------------------------------------------------------------------
# summarize_node_tree
# ---------------------------------------------------------------------------

async def summarize_node_tree(
    db,
    user_id: str,
    node_id: str,
    max_nodes: int = 200,
) -> dict:
    """
    Return a summary of the tree rooted at (or containing) node_id.
    Includes counts by kind, lifecycle, outcome.
    """
    # Access check is performed inside get_node_tree
    tree = await get_node_tree(db, user_id, node_id, max_nodes=max_nodes)
    nodes = tree["nodes"]

    kind_counts: dict[str, int] = {}
    lifecycle_counts: dict[str, int] = {}
    outcome_counts: dict[str, int] = {}

    for n in nodes:
        k = n.get("kind", "untyped")
        kind_counts[k] = kind_counts.get(k, 0) + 1
        lc = n.get("lifecycle", "staged")
        lifecycle_counts[lc] = lifecycle_counts.get(lc, 0) + 1
        oc = n.get("outcome")
        if oc:
            outcome_counts[oc] = outcome_counts.get(oc, 0) + 1

    return {
        "anchor_node_id": node_id,
        "root_node_ids": tree["root_node_ids"],
        "node_count": tree["node_count"],
        "kind_counts": kind_counts,
        "lifecycle_counts": lifecycle_counts,
        "outcome_counts": outcome_counts,
        "nodes": nodes,
    }


# ---------------------------------------------------------------------------
# remote artifacts
# ---------------------------------------------------------------------------

_NAT64_PREFIX = ipaddress.ip_network("64:ff9b::/96")
_TRANSLATION_PREFIXES = (
    _NAT64_PREFIX,
    ipaddress.ip_network("64:ff9b:1::/48"),
    ipaddress.ip_network("2002::/16"),  # 6to4
    ipaddress.ip_network("2001::/32"),  # Teredo
)
_REMOTE_ARTIFACT_MAX_BYTES = 10 * 1024 * 1024
_REMOTE_ARTIFACT_TIMEOUT = 15.0
_REMOTE_ARTIFACT_MAX_REDIRECTS = 5


def _is_non_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True for anything but a plain globally routable unicast address.

    ``is_global`` covers the per-flag checks plus the IANA special-purpose
    ranges they miss (100.64.0.0/10 CGNAT, 192.0.0.0/24, ...). An IPv4-mapped
    IPv6 literal is unwrapped so ``::ffff:127.0.0.1`` is judged as 127.0.0.1.
    NAT64, 6to4, and Teredo translation/tunnel prefixes are rejected outright;
    their IANA special-purpose classification differs across Python versions.
    """
    if ip.version == 6:
        if any(ip in prefix for prefix in _TRANSLATION_PREFIXES):
            return True
        mapped = ip.ipv4_mapped
        if mapped is not None:
            # Classify the actual destination, not both the IPv6 wrapper and
            # IPv4 target. Older Python versions mark all wrappers reserved.
            ip = mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
        or not ip.is_global
    )


def _assert_public_url(url: str) -> None:
    """Validate a URL without fetching; fetches must also pin these addresses."""
    _public_artifact_addresses(url)


def _public_artifact_addresses(
    url: str,
) -> tuple[urllib.parse.ParseResult, tuple[str, ...]]:
    if any(ord(char) <= 32 or ord(char) == 127 for char in url):
        raise ValueError(
            "Remote artifact URL contains whitespace or control characters"
        )
    parsed = urllib.parse.urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("Remote artifact URL must be public HTTPS")
    host = parsed.hostname
    if not host:
        raise ValueError("Remote artifact URL has no host")
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError("Remote artifact URL has an invalid port")
    try:
        infos = socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ValueError(f"Remote artifact host does not resolve: {host}") from exc
    addresses = []
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if _is_non_public_ip(ip):
            raise ValueError("Remote artifact host resolves to a non-public address")
        addresses.append(str(ip))
    if not addresses:
        raise ValueError("Remote artifact host has no resolved addresses")
    return parsed, tuple(dict.fromkeys(addresses))


class _PinnedArtifactHTTPSConnection(http.client.HTTPSConnection):
    """Direct vetted-IP transport; original host remains TLS/SNI/HTTP authority.

    http.client does not consult ambient proxy settings. DNS is resolved only
    by the admission helper, never again for a hostname during socket connect.
    The deadline closes active I/O, including a trickling response/header.
    System DNS resolution itself remains subject to the OS resolver timeout.
    """

    def __init__(
        self, host: str, port: int, addresses: tuple[str, ...], deadline: float
    ):
        super().__init__(host, port, context=ssl.create_default_context())
        self._addresses = addresses
        self._deadline = deadline
        self._deadline_timer: threading.Timer | None = None
        # HTTPConnection may logically close itself while HTTPResponse still
        # owns the socket file (e.g. Connection: close). Keep the deadline alive
        # across that ownership transfer until the fetch explicitly finishes.
        self._active_socket: socket.socket | None = None

    def _abort_socket(self) -> None:
        current = self._active_socket
        if current is not None:
            try:
                current.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            current.close()

    def connect(self) -> None:
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Remote artifact request timed out")
        self._deadline_timer = threading.Timer(remaining, self._abort_socket)
        self._deadline_timer.daemon = True
        self._deadline_timer.start()
        failure: OSError | None = None
        for address in self._addresses:
            remaining = self._deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Remote artifact request timed out")
            try:
                self.sock = socket.create_connection(
                    (address, self.port), timeout=remaining
                )
                self._active_socket = self.sock
                self.sock = self._context.wrap_socket(
                    self.sock,
                    server_hostname=self.host,
                    do_handshake_on_connect=False,
                )
                self._active_socket = self.sock
                remaining = self._deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Remote artifact request timed out")
                self.sock.settimeout(remaining)
                self.sock.do_handshake()
                if time.monotonic() >= self._deadline:
                    raise TimeoutError("Remote artifact request timed out")
                return
            except OSError as exc:
                failure = exc
                if self.sock is not None:
                    self.sock.close()
                    self.sock = None
                self._active_socket = None
        raise failure or OSError("Remote artifact connection failed")

    def finish(self) -> None:
        if self._deadline_timer is not None:
            self._deadline_timer.cancel()
        self._abort_socket()
        self._active_socket = None
        super().close()


def _fetch_https_json(url: str) -> Any:
    deadline = time.monotonic() + _REMOTE_ARTIFACT_TIMEOUT
    for redirects in range(_REMOTE_ARTIFACT_MAX_REDIRECTS + 1):
        parsed, addresses = _public_artifact_addresses(url)
        connection = _PinnedArtifactHTTPSConnection(
            parsed.hostname, parsed.port or 443, addresses, deadline
        )
        response = None
        try:
            path = urllib.parse.urlunparse(
                ("", "", parsed.path or "/", parsed.params, parsed.query, "")
            )
            connection.request("GET", path, headers={"Accept": "application/json"})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                target = response.getheader("Location")
                if not target or redirects == _REMOTE_ARTIFACT_MAX_REDIRECTS:
                    raise ValueError("Remote artifact redirect limit or missing target")
                url = urllib.parse.urljoin(url, target)
                continue
            if response.status != 200:
                raise ValueError("Remote artifact server did not return HTTP 200")
            declared = response.getheader("Content-Length")
            if declared is not None and (
                not declared.isdecimal() or int(declared) > _REMOTE_ARTIFACT_MAX_BYTES
            ):
                raise ValueError(
                    "Remote artifact response exceeds the byte limit or has invalid length"
                )
            raw = bytearray()
            while True:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Remote artifact request timed out")
                chunk = response.read1(
                    min(65536, _REMOTE_ARTIFACT_MAX_BYTES + 1 - len(raw))
                )
                if time.monotonic() >= deadline:
                    raise TimeoutError("Remote artifact request timed out")
                raw.extend(chunk)
                if len(raw) > _REMOTE_ARTIFACT_MAX_BYTES:
                    raise ValueError("Remote artifact response exceeds the byte limit")
                if not chunk:
                    break
            if declared is not None and len(raw) != int(declared):
                raise ValueError(
                    "Remote artifact response ended before its declared length"
                )
            return json.loads(raw.decode("utf-8"))
        except (
            OSError,
            http.client.HTTPException,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            # Avoid reflecting signed URLs, userinfo, or response fragments.
            raise ValueError(
                "Remote artifact HTTPS fetch failed or returned invalid JSON"
            ) from exc
        finally:
            connection.finish()
            if response is not None:
                response.close()
    raise ValueError("Remote artifact redirect limit exceeded")


async def _find_remote_artifact(
    db,
    node_id: str,
    remote_artifact_id: str,
) -> dict[str, Any] | None:
    cursor = await db.execute(
        "SELECT * FROM artifacts WHERE node_id = ? AND artifact_type = 'json' ORDER BY created_at DESC",
        (node_id,),
    )
    rows = await cursor.fetchall()
    for row in rows:
        artifact = dict(row)
        metadata = _json_loads(artifact.get("metadata"), {})
        if metadata.get("remote_artifact_id") == remote_artifact_id:
            return artifact
    return None


def _remote_artifact_is_fresh(row: dict[str, Any], cache_ttl_seconds: int) -> bool:
    metadata = _json_loads(row.get("metadata"), {})
    fetched_at = metadata.get("fetched_at") or row.get("created_at")
    if not fetched_at:
        return False
    try:
        fetched_dt = datetime.fromisoformat(str(fetched_at).replace("Z", "+00:00"))
    except ValueError:
        return False
    age_seconds = (datetime.utcnow() - fetched_dt.replace(tzinfo=None)).total_seconds()
    return age_seconds <= max(0, cache_ttl_seconds)


def _remote_summary(
    row: dict[str, Any],
    *,
    cached: bool,
    refreshed: bool,
) -> dict[str, Any]:
    artifact = _serialize_artifact_row(row)
    metadata = artifact["metadata"]
    return {
        "artifact": artifact,
        "remote_artifact": {
            "remote_artifact_id": metadata.get("remote_artifact_id"),
            "artifact_id": artifact["artifact_id"],
            "title": artifact["title"],
            "url": metadata.get("url"),
            "rows_path": metadata.get("rows_path"),
            "row_id": metadata.get("row_id"),
            "row_count": metadata.get("row_count", 0),
            "row_ids": metadata.get("row_ids", []),
            "fetched_at": metadata.get("fetched_at"),
            "cache_ttl_seconds": metadata.get("cache_ttl_seconds"),
        },
        "cached": cached,
        "refreshed": refreshed,
    }


async def resolve_remote_artifact(
    db,
    user_id: str,
    node_id: str,
    *,
    remote_artifact_id: str,
    title: str,
    url: str,
    rows_path: str,
    row_id: str,
    cache_ttl_seconds: int = 60,
    force_refresh: bool = False,
) -> dict:
    """Resolve or refresh a public JSON remote artifact as a durable artifact.

    This intentionally uses the existing ``artifacts`` table instead of a new
    migration: the fetched JSON is the artifact payload and the remote identity
    and row index live in artifact metadata.
    """
    await require_node_access(db, user_id, node_id, "write")
    if await node_repo.get_node(db, node_id) is None:
        raise ValueError(f"Node {node_id} not found")

    existing = await _find_remote_artifact(db, node_id, remote_artifact_id)
    if existing is not None and not force_refresh:
        if _remote_artifact_is_fresh(existing, cache_ttl_seconds):
            return _remote_summary(existing, cached=True, refreshed=False)

    # DNS resolution plus the bounded HTTPS fetch are blocking; keep them off
    # the event loop so a slow remote host cannot stall the whole worker.
    payload = await asyncio.to_thread(_fetch_https_json, url)
    rows = _get_dotted(payload, rows_path)
    if not isinstance(rows, list):
        raise ValueError("rows_path must resolve to a list")
    row_ids = []
    for row in rows:
        value = _get_dotted(row, row_id)
        if value is not None:
            row_ids.append(str(value))

    now = _now()
    metadata = {
        "remote_artifact": True,
        "remote_artifact_id": remote_artifact_id,
        "url": url,
        "rows_path": rows_path,
        "row_id": row_id,
        "row_count": len(rows),
        "row_ids": row_ids,
        "cache_ttl_seconds": cache_ttl_seconds,
        "fetched_at": now,
    }

    if existing is None:
        artifact_id = str(uuid.uuid4())
        await db.execute(
            """INSERT INTO artifacts
               (artifact_id, node_id, artifact_type, title, note, payload,
                metadata, execution_id, storage_path, created_at)
               VALUES (?, ?, 'json', ?, ?, ?, ?, NULL, NULL, ?)""",
            (
                artifact_id,
                node_id,
                title,
                "Remote artifact cache",
                json.dumps(payload),
                json.dumps(metadata),
                now,
            ),
        )
    else:
        artifact_id = existing["artifact_id"]
        await db.execute(
            """UPDATE artifacts
               SET title = ?, payload = ?, metadata = ?
               WHERE artifact_id = ? AND node_id = ?""",
            (
                title,
                json.dumps(payload),
                json.dumps(metadata),
                artifact_id,
                node_id,
            ),
        )

    row = await artifact_repo.get_artifact(db, artifact_id)
    node_row = await node_repo.get_node(db, node_id)
    if node_row is not None:
        await node_repo.update_node(db, node_id, {
            "revision": node_row["revision"] + 1,
            "updated_at": now,
        })
    await db.commit()
    if row is None:
        row = await artifact_repo.get_artifact(db, artifact_id)
    assert row is not None
    row["payload"] = json.dumps(payload)
    row["metadata"] = json.dumps(metadata)
    row["title"] = title
    return _remote_summary(row, cached=False, refreshed=True)
