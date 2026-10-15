"""
Node CRUD routes -- create, read, update, delete, branch, merge, and query
research-graph nodes.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse

from atlas_graph.cache.response_cache import BytesResponseCache, accepts_gzip
from atlas_graph import config
from atlas_graph.dependencies import get_current_user, get_db, optional_auth
from atlas_graph.models.node import (
    AddParentRequest,
    BranchNodeRequest,
    BulkDeleteRequest,
    BulkDeleteResponse,
    CommitNodeRequest,
    MergeNodesRequest,
    RemoveParentRequest,
    StageNodeCreateRequest,
    StageNodeUpdateRequest,
)
from atlas_graph.services import node_service

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

from atlas_graph.routes._errors import service_error_to_http as _service_error_to_http


def _require_public_route() -> None:
    if not config.PUBLIC_GRAPHS_ENABLED:
        raise HTTPException(status_code=404, detail="Not found")


# ---------------------------------------------------------------------------
# POST /api/nodes/stage-create
# ---------------------------------------------------------------------------

@router.post("/api/nodes/stage-create", status_code=status.HTTP_201_CREATED)
async def stage_create(
    req: StageNodeCreateRequest,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await node_service.stage_create(db, user["user_id"], req)
    except ValueError as e:
        raise _service_error_to_http(e)


# ---------------------------------------------------------------------------
# POST /api/nodes/stage-update
# ---------------------------------------------------------------------------

@router.post("/api/nodes/stage-update")
async def stage_update(
    req: StageNodeUpdateRequest,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await node_service.stage_update(db, user["user_id"], req)
    except ValueError as e:
        raise _service_error_to_http(e)


# ---------------------------------------------------------------------------
# POST /api/nodes/commit
# ---------------------------------------------------------------------------

@router.post("/api/nodes/commit")
async def commit_node(
    req: CommitNodeRequest,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        result = await node_service.commit_node(db, user["user_id"], req)
    except ValueError as e:
        raise _service_error_to_http(e)

    if result is None:
        # Fetch current node to explain WHY commit failed
        try:
            node = await node_service.get_node(db, user["user_id"], req.node_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Node not found",
            )

        reasons: list[str] = []

        # Check revision mismatch first
        if node.get("revision") != req.expected_revision:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Revision mismatch - refresh and try again",
            )

        kind = node.get("kind", "untyped")
        if kind == "untyped":
            reasons.append("Set kind to 'insight' or 'empirical'")
        if not node.get("outcome"):
            reasons.append("Set outcome (completed/failed/canceled)")
        if not node.get("summary"):
            reasons.append("Add a summary")
        if kind == "insight" and not node.get("insights"):
            reasons.append("Add at least one insight")
        if kind == "empirical" and not node.get("hypothesis"):
            reasons.append("Add a hypothesis")
        if kind == "empirical" and node.get("insights") and len(node["insights"]) > 0:
            reasons.append("Empirical nodes must not have insights")

        detail = (
            "Cannot commit: " + "; ".join(reasons)
            if reasons
            else "Revision mismatch - refresh and try again"
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail,
        )
    return result


# ---------------------------------------------------------------------------
# POST /api/nodes/branch
# ---------------------------------------------------------------------------

@router.post("/api/nodes/branch", status_code=status.HTTP_201_CREATED)
async def branch_node(
    req: BranchNodeRequest,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await node_service.branch_node(db, user["user_id"], req)
    except ValueError as e:
        raise _service_error_to_http(e)


# ---------------------------------------------------------------------------
# POST /api/nodes/merge
# ---------------------------------------------------------------------------

@router.post("/api/nodes/merge", status_code=status.HTTP_201_CREATED)
async def merge_nodes(
    req: MergeNodesRequest,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await node_service.merge_nodes(db, user["user_id"], req)
    except ValueError as e:
        raise _service_error_to_http(e)


# ---------------------------------------------------------------------------
# POST /api/nodes/add-parent
# ---------------------------------------------------------------------------

@router.post("/api/nodes/add-parent")
async def add_parent(
    req: AddParentRequest,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await node_service.add_parent(db, user["user_id"], req)
    except ValueError as e:
        raise _service_error_to_http(e)


# ---------------------------------------------------------------------------
# POST /api/nodes/remove-parent
# ---------------------------------------------------------------------------

@router.post("/api/nodes/remove-parent")
async def remove_parent(
    req: RemoveParentRequest,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await node_service.remove_parent(db, user["user_id"], req)
    except ValueError as e:
        raise _service_error_to_http(e)


# ---------------------------------------------------------------------------
# DELETE /api/nodes/{node_id}
# ---------------------------------------------------------------------------

@router.delete(
    "/api/nodes/{node_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_node(
    node_id: str,
    delete_mode: str = Query("cascade"),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        await node_service.delete_node(db, user["user_id"], node_id, delete_mode)
    except ValueError as e:
        raise _service_error_to_http(e)


# ---------------------------------------------------------------------------
# POST /api/nodes/bulk-delete
# ---------------------------------------------------------------------------

@router.post("/api/nodes/bulk-delete", response_model=BulkDeleteResponse)
async def bulk_delete_nodes(
    req: BulkDeleteRequest,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    return await node_service.bulk_delete_nodes(db, user["user_id"], req.node_ids)


# ---------------------------------------------------------------------------
# GET /api/nodes  (list)
# ---------------------------------------------------------------------------

@router.get("/api/nodes")
async def list_nodes(
    scope: Literal["owned_or_shared_private"] | None = Query(None),
    owners: Optional[str] = Query(None, description="Comma-separated owner user IDs"),
    writers: Optional[str] = Query(None, description="Comma-separated writer user IDs"),
    visibility: Optional[str] = Query(None),
    kind: Optional[str] = Query(None),
    lifecycle: Optional[str] = Query(None),
    outcome: Optional[str] = Query(None),
    root_only: Optional[bool] = Query(None),
    repo_url: Optional[str] = Query(None),
    tag_id: Optional[str] = Query(None, description="Filter nodes by tag assignment"),
    title: Optional[str] = Query(None, description="Filter nodes by title substring"),
    projection: str = Query("core"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    owners_list = owners.split(",") if owners else None
    writers_list = writers.split(",") if writers else None

    return await node_service.list_nodes(
        db,
        user["user_id"],
        scope=scope,
        owners=owners_list,
        writers=writers_list,
        visibility=visibility,
        kind=kind,
        lifecycle=lifecycle,
        outcome=outcome,
        root_only=root_only,
        repo_url=repo_url,
        tag_id=tag_id,
        title=title,
        projection=projection,
        page=page,
        per_page=per_page,
    )


# ---------------------------------------------------------------------------
# GET /api/nodes/explore  (public - no auth required)
# ---------------------------------------------------------------------------

@router.get("/api/nodes/explore")
async def explore_public_nodes(
    request: Request,
    kind: Optional[str] = Query(None),
    lifecycle: Optional[str] = Query(None),
    outcome: Optional[str] = Query(None),
    title: Optional[str] = Query(None, description="Search by title substring"),
    root_only: bool = Query(False),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict | None = Depends(optional_auth),
):
    """List public nodes without requiring authentication.

    Always forces ``visibility='public'`` so only publicly-shared nodes are
    returned.  When the caller is authenticated their user_id is forwarded
    for consistent access-control bookkeeping; otherwise a sentinel
    ``__anonymous__`` id is used.
    """
    _require_public_route()
    user_id = user["user_id"] if user else "__anonymous__"
    # Output is forced to public nodes and is viewer-independent; cache the
    # anonymous view (the common case for this unauthenticated list).
    key = None
    if user is None:
        key = f"{kind}:{lifecycle}:{outcome}:{title}:{root_only}:{page}:{per_page}"
        hit = _nodes_list_cache.get(key, want_gzip=accepts_gzip(request))
        if hit is not None:
            return hit
    data = await node_service.list_nodes(
        db,
        user_id,
        visibility="public",
        kind=kind,
        lifecycle=lifecycle,
        outcome=outcome,
        root_only=root_only,
        # Explore surfaces full public graphs only -- exclude standalone
        # public nodes (a public root with no children is a single-node graph).
        require_children=True,
        title=title,
        projection="topology",
        page=page,
        per_page=per_page,
    )
    if key is not None:
        return _nodes_list_cache.put(key, data, want_gzip=accepts_gzip(request))
    return data


@router.get("/api/nodes/explore/graphs")
async def explore_public_graphs(
    request: Request,
    title: Optional[str] = Query(None, description="Search title, summary, slug, or author"),
    sort: str = Query("trending", description="trending | top | forks | recent | new"),
    has_paper: Optional[bool] = Query(None),
    has_code: Optional[bool] = Query(None),
    forked: Optional[bool] = Query(None),
    autoresearch: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(24, ge=1, le=100),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict | None = Depends(optional_auth),
):
    """Public archive of whole graphs (GitHub x arXiv): authors, stars, forks,
    paper links, code presence. Only project roots with children appear."""
    _require_public_route()
    user_id = user["user_id"] if user else None
    # Anonymous cards are viewer-independent (no per-viewer star state) and this
    # is the launch's hottest endpoint — serve from the bytes cache. Authenticated
    # callers get the live, per-viewer "starred" set (never cached).
    key = None
    if user_id is None:
        key = f"{title}:{sort}:{has_paper}:{has_code}:{forked}:{autoresearch}:{page}:{per_page}"
        hit = _cards_cache.get(key, want_gzip=accepts_gzip(request))
        if hit is not None:
            return hit
    data = await node_service.explore_public_graph_cards(
        db,
        user_id=user_id,
        title=title,
        has_paper=has_paper,
        has_code=has_code,
        forked=forked,
        autoresearch=autoresearch,
        sort=sort,
        page=page,
        per_page=per_page,
    )
    if key is not None:
        return _cards_cache.put(key, data, want_gzip=accepts_gzip(request))
    return data


@router.get("/api/nodes/explore/{node_id}/social")
async def explore_public_graph_social(
    request: Request,
    node_id: str,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict | None = Depends(optional_auth),
):
    """Star/fork counts for a public graph (no auth required to read)."""
    _require_public_route()
    user_id = user["user_id"] if user else None
    # For anonymous viewers ``viewer_has_starred`` is always false, so the
    # response is viewer-independent and cacheable; authenticated callers get the
    # live per-viewer star state.
    if user_id is None:
        hit = _social_cache.get(node_id, want_gzip=accepts_gzip(request))
        if hit is not None:
            return hit
    try:
        data = await node_service.public_graph_social(db, node_id, user_id)
    except ValueError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail="Public graph not found")
        raise _service_error_to_http(e)
    if user_id is None:
        return _social_cache.put(node_id, data, want_gzip=accepts_gzip(request))
    return data


@router.get("/api/nodes/explore/{node_id}/artifacts")
async def explore_public_node_artifacts(
    request: Request,
    node_id: str,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict | None = Depends(optional_auth),
):
    """List a public node's artifacts/evidence (results, figures, logs)."""
    _require_public_route()
    user_id = user["user_id"] if user else None
    # The artifact list of a public node is viewer-independent; cache anonymous.
    if user_id is None:
        hit = _artifacts_cache.get(node_id, want_gzip=accepts_gzip(request))
        if hit is not None:
            return hit
    try:
        data = await node_service.public_node_artifacts(db, node_id, user_id)
    except ValueError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail="Public graph not found")
        raise _service_error_to_http(e)
    if user_id is None:
        return _artifacts_cache.put(node_id, data, want_gzip=accepts_gzip(request))
    return data


@router.get("/api/nodes/explore/{node_id}/artifacts/{artifact_id}/download")
async def explore_public_node_artifact_download(
    node_id: str,
    artifact_id: str,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict | None = Depends(optional_auth),
):
    """Download one public artifact (302 to a signed/remote URL, else bytes)."""
    _require_public_route()
    user_id = user["user_id"] if user else None
    try:
        blob = await node_service.resolve_public_artifact_blob(
            db, node_id, artifact_id, user_id
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="blob not found")
    except ValueError:
        raise HTTPException(status_code=404, detail="artifact not found")
    if "redirect" in blob:
        return RedirectResponse(url=blob["redirect"])
    from atlas_graph.services.blob_serve import safe_blob_response

    # Public, unauthenticated download of user-uploaded bytes — force a safe
    # download (never render html/svg inline on our origin). XSS hardening.
    return safe_blob_response(
        content=blob["bytes"],
        media_type=blob["media_type"],
        filename=blob["filename"],
        inline=False,
    )


@router.post("/api/nodes/{node_id}/star")
async def star_graph(
    node_id: str,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Star the graph containing this node (resolves to the project root)."""
    try:
        return await node_service.set_graph_star(db, user["user_id"], node_id, starred=True)
    except ValueError as e:
        raise _service_error_to_http(e)


@router.delete("/api/nodes/{node_id}/star")
async def unstar_graph(
    node_id: str,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Remove your star from the graph containing this node."""
    try:
        return await node_service.set_graph_star(db, user["user_id"], node_id, starred=False)
    except ValueError as e:
        raise _service_error_to_http(e)


# Serialized-bytes caches for the hot public READ surface. These responses are
# identical across anonymous callers and change rarely; caching the bytes lets a
# hit skip the DB round-trips AND JSON encoding (the tree encode alone was ~37% of
# event-loop time under load). This frees the 12-conn DB pool for writes/cold
# paths and raises the per-worker throughput ceiling. See response_cache.py.
_public_tree_cache = BytesResponseCache(ttl=15.0, max_entries=128)
_cards_cache = BytesResponseCache(ttl=10.0, max_entries=256)
_nodes_list_cache = BytesResponseCache(ttl=10.0, max_entries=256)
_social_cache = BytesResponseCache(ttl=12.0, max_entries=512)
_artifacts_cache = BytesResponseCache(ttl=15.0, max_entries=256)

_PUBLIC_READ_CACHES = (
    _public_tree_cache,
    _cards_cache,
    _nodes_list_cache,
    _social_cache,
    _artifacts_cache,
)


def _reset_public_caches_for_tests() -> None:
    """Drop all public-read caches. Each test has its own isolated DB but shares
    the process, so the in-process caches must be cleared between tests to avoid
    one test's response leaking into another. No-op cost in production."""
    for cache in _PUBLIC_READ_CACHES:
        cache.clear()


@router.get("/api/nodes/explore/{node_id}/tree")
async def explore_public_graph_tree(
    request: Request,
    node_id: str,
    projection: str = Query("topology"),
    max_nodes: int = Query(5000, ge=1, le=10000),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Read a public root graph without requiring authentication.

    Public explore is graph-first: the listed object is the root node, and
    opening it shows that graph's connected tree.  Non-root nodes remain
    accessible through the authenticated node detail page only.
    """
    _require_public_route()
    gz = accepts_gzip(request)
    key = f"{node_id}:{projection}:{max_nodes}"
    hit = _public_tree_cache.get(key, want_gzip=gz)
    if hit is not None:
        return hit
    try:
        data = await node_service.get_public_root_tree(
            db,
            node_id,
            projection=projection,
            max_nodes=max_nodes,
        )
    except HTTPException:
        raise
    except ValueError as e:
        if "Public graph not found" in str(e):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Public graph not found",
            )
        raise _service_error_to_http(e)
    return _public_tree_cache.put(key, data, want_gzip=gz)


# ---------------------------------------------------------------------------
# Public code browsing for shared nodes (no auth).
#   GET /api/nodes/explore/{node_id}/repo/tree
#   GET /api/nodes/explore/{node_id}/repo/read
#
# This is how a viewer of a PUBLIC graph reaches the exact code behind a
# node. Two safety properties:
#   1. View-gated by the same rule as the rest of the public surface, so
#      private nodes return 404 (and never leak their existence).
#   2. Public-repo-ONLY: we use unauthenticated / backend-token GitHub
#      access and NEVER the node owner's personal token, so a user's
#      private repos can never be exposed through a public node.
# The ref defaults to the node's pinned ``head_commit_sha`` so viewers see
# the precise commit captured for the node, not whatever HEAD is now.
# ---------------------------------------------------------------------------


async def _public_node_repo(
    db: aiosqlite.Connection, node_id: str, user: dict | None
) -> dict[str, str]:
    """Resolve (owner, repo, default_ref) for a publicly-viewable node."""
    _require_public_route()
    from atlas_graph.auth.access_check import check_node_access
    from atlas_graph.db.repos import node_repo
    from atlas_graph.services.repo_state_service import _parse_repo_url

    viewer = user["user_id"] if user else "__anonymous__"
    try:
        node_id = await node_service._resolve_public_node_ref(db, node_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="node not found")
    allowed = await check_node_access(db, viewer, node_id, "view")
    if not allowed:
        # None (missing) and False (private) both look like "not found" to
        # an unauthorized caller - don't leak that a private node exists.
        raise HTTPException(status_code=404, detail="node not found")

    row = await node_repo.get_node(db, node_id)
    if row is None:
        raise HTTPException(status_code=404, detail="node not found")
    repo_url = row.get("repo_url")
    if not repo_url:
        raise HTTPException(status_code=404, detail="node has no repo linked")
    parsed = _parse_repo_url(repo_url)
    if parsed is None:
        raise HTTPException(status_code=400, detail=f"unrecognized repo_url: {repo_url}")
    owner, repo = parsed
    default_ref = row.get("head_commit_sha") or row.get("branch_name") or "main"
    return {"owner": owner, "repo": repo, "default_ref": default_ref}


@router.get("/api/nodes/explore/{node_id}/repo/tree")
async def explore_public_node_repo_tree(
    node_id: str,
    path: str = Query(""),
    ref: str | None = Query(None),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict | None = Depends(optional_auth),
):
    """List a public node's repo contents (no auth, public repos only)."""
    from atlas_graph.clients import github_client

    info = await _public_node_repo(db, node_id, user)
    effective_ref = ref or info["default_ref"]
    try:
        entries = await github_client.tree(
            f"{info['owner']}/{info['repo']}", path or "", ref=effective_ref,
            server_token_fallback=False,
        )
    except github_client.GitHubError as exc:
        if exc.status in (401, 403, 404):
            raise HTTPException(
                status_code=404, detail="repo not public or path not found",
            )
        raise HTTPException(status_code=502, detail=f"github: {exc}")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"github: {exc}")
    return {
        "repo": f"{info['owner']}/{info['repo']}",
        "ref": effective_ref,
        "path": path or "",
        "entries": entries,
    }


@router.get("/api/nodes/explore/{node_id}/repo/read")
async def explore_public_node_repo_read(
    node_id: str,
    path: str = Query(...),
    ref: str | None = Query(None),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict | None = Depends(optional_auth),
):
    """Read a file from a public node's repo (no auth, public repos only)."""
    from atlas_graph.clients import github_client

    info = await _public_node_repo(db, node_id, user)
    effective_ref = ref or info["default_ref"]
    try:
        result = await github_client.read_file(
            f"{info['owner']}/{info['repo']}", path, ref=effective_ref,
            server_token_fallback=False,
        )
    except github_client.GitHubError as exc:
        if exc.status in (401, 403, 404):
            raise HTTPException(
                status_code=404, detail="repo not public or file not found",
            )
        raise HTTPException(status_code=502, detail=f"github: {exc}")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"github: {exc}")
    return {
        "repo": f"{info['owner']}/{info['repo']}",
        "ref": effective_ref,
        "path": path,
        **result,
    }


# ---------------------------------------------------------------------------
# GET /api/nodes/resolve-slug/{slug_name}
# ---------------------------------------------------------------------------
# NOTE: This must be declared BEFORE the /{node_id} catch-all to avoid
# "resolve-slug" being interpreted as a node_id.

@router.get("/api/nodes/resolve-slug/{slug_name}")
async def resolve_node_slug(
    slug_name: str,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    return await node_service.resolve_node_slug(db, user["user_id"], slug_name)


# ---------------------------------------------------------------------------
# GET /api/nodes/{node_id}
# ---------------------------------------------------------------------------

@router.get("/api/nodes/{node_id}")
async def get_node(
    node_id: str,
    projection: str = Query("core"),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await node_service.get_node(db, user["user_id"], node_id, projection)
    except ValueError as e:
        raise _service_error_to_http(e)


# ---------------------------------------------------------------------------
# GET /api/nodes/{node_id}/tree
# ---------------------------------------------------------------------------

# Small in-memory cache for get_node_tree responses. Keyed by
# (user_id, node_id, projection, max_nodes). TTL of 15s matches the
# frontend's typical cadence (refresh on tab focus, project switch)
# and any meaningful graph change (stage_create / commit) invalidates
# by revision bump anyway - so stale-for-15s is harmless.
import time as _time
_TREE_TTL_S = 15.0
_TREE_CACHE_MAX = 128
_tree_cache: dict[tuple, tuple[float, Any]] = {}


def _tree_cache_key(user_id: str, node_id: str, projection: str, max_nodes: int):
    return (user_id, node_id, projection, max_nodes)


def _tree_cache_invalidate(node_id: str) -> None:
    """Drop every cached tree that mentions this node_id - used after
    commit/stage/edit mutations bubble from services."""
    stale = [k for k in _tree_cache if k[1] == node_id]
    for k in stale:
        _tree_cache.pop(k, None)


@router.get("/api/nodes/{node_id}/tree")
async def get_node_tree(
    node_id: str,
    projection: str = Query("core"),
    max_nodes: int = Query(5000, ge=1, le=10000),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    key = _tree_cache_key(user["user_id"], node_id, projection, max_nodes)
    now = _time.monotonic()
    cached = _tree_cache.get(key)
    if cached and (now - cached[0]) < _TREE_TTL_S:
        return cached[1]

    try:
        result = await node_service.get_node_tree(
            db, user["user_id"], node_id, projection, max_nodes
        )
    except ValueError as e:
        raise _service_error_to_http(e)

    # LRU cap by simple size-based eviction of oldest entry.
    if len(_tree_cache) >= _TREE_CACHE_MAX:
        oldest = min(_tree_cache, key=lambda k: _tree_cache[k][0])
        _tree_cache.pop(oldest, None)
    _tree_cache[key] = (now, result)
    return result


# ---------------------------------------------------------------------------
# GET /api/nodes/{node_id}/ancestry
# ---------------------------------------------------------------------------

@router.get("/api/nodes/{node_id}/ancestry")
async def get_node_ancestry(
    node_id: str,
    projection: str = Query("core"),
    max_depth: int = Query(256, ge=1, le=1000),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await node_service.get_node_ancestry(
            db, user["user_id"], node_id, projection, max_depth
        )
    except ValueError as e:
        raise _service_error_to_http(e)


# ---------------------------------------------------------------------------
# GET /api/nodes/{node_id}/summarize
# ---------------------------------------------------------------------------

@router.get("/api/nodes/{node_id}/summarize")
async def summarize_node_tree(
    node_id: str,
    max_nodes: int = Query(200, ge=1, le=10000),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await node_service.summarize_node_tree(
            db, user["user_id"], node_id, max_nodes
        )
    except ValueError as e:
        raise _service_error_to_http(e)
