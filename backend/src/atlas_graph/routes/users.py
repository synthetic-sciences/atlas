"""Public researcher profiles + directory (read-only, no auth required).

The collaboration surface: anyone can browse who publishes research graphs,
open a researcher's profile, and see their public graphs — GitHub-style
profiles for the research archive. Handles resolve via ``github_username``.
"""

from __future__ import annotations

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query

from atlas_graph.dependencies import get_db, optional_auth
from atlas_graph import config
from atlas_graph.db.repos import user_repo
from atlas_graph.services import node_service

router = APIRouter()


def _require_public_route() -> None:
    if not config.PUBLIC_GRAPHS_ENABLED:
        raise HTTPException(status_code=404, detail="Not found")


@router.get("/api/researchers")
async def list_researchers(
    q: str | None = Query(None, description="search by handle / name"),
    sort: str = Query("graphs", description="graphs | new"),
    page: int = Query(1, ge=1),
    per_page: int = Query(48, ge=1, le=100),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict | None = Depends(optional_auth),
):
    """Search researchers who have published a public graph.

    Discovery is search-driven and limited to users with >=1 public graph, so
    accounts that never publish stay unlisted. An empty ``q`` returns nothing.
    """
    _require_public_route()
    return await node_service.list_public_researchers(
        db, q=q, sort=sort, page=page, per_page=per_page
    )


@router.get("/api/users/{handle}")
async def public_user_profile(
    handle: str,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict | None = Depends(optional_auth),
):
    """Public profile for a researcher, resolved by handle (github_username)."""
    _require_public_route()
    owner = await user_repo.get_user_by_github_username(db, handle)
    if owner is None:
        raise HTTPException(status_code=404, detail="researcher not found")
    count = await node_service.count_public_graphs_for_owner(db, owner["user_id"])
    # Anti-scrape: a profile only exists publicly once the user has published
    # at least one public graph. Otherwise it's indistinguishable from absent.
    if count <= 0:
        raise HTTPException(status_code=404, detail="researcher not found")
    return node_service.public_profile_shape(owner, count)


@router.get("/api/users/{handle}/graphs")
async def public_user_graphs(
    handle: str,
    sort: str = Query("recent", description="trending | top | forks | recent | new"),
    page: int = Query(1, ge=1),
    per_page: int = Query(24, ge=1, le=100),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict | None = Depends(optional_auth),
):
    """A researcher's public graphs (same card shape as Explore)."""
    _require_public_route()
    owner = await user_repo.get_user_by_github_username(db, handle)
    if owner is None:
        raise HTTPException(status_code=404, detail="researcher not found")
    viewer_id = user["user_id"] if user else None
    return await node_service.explore_public_graph_cards(
        db,
        user_id=viewer_id,
        owner_user_id=owner["user_id"],
        sort=sort,
        page=page,
        per_page=per_page,
    )
