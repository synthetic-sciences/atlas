"""Public browse endpoints under /api/v1 for the Atlas CLI.

The web app reads the discovery surfaces from /api/* (researchers, explore
graphs, competitions). The CLI talks to /api/v1/*, so these thin, public
(optional_auth) endpoints re-expose the same services for `atlas explore`,
`atlas researchers`, and `atlas competitions`. No logic is duplicated — they
delegate to node_service / competition_service.
"""
from __future__ import annotations

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query

from atlas_graph.dependencies import get_db, optional_auth
from atlas_graph import config
from atlas_graph.services import competition_service, node_service

router = APIRouter()


def _require_public_route() -> None:
    if not config.PUBLIC_GRAPHS_ENABLED:
        raise HTTPException(status_code=404, detail="Not found")


@router.get("/api/v1/explore")
async def cli_explore_graphs(
    query: str | None = Query(None, description="search title / summary / author"),
    sort: str = Query("trending", description="trending | top | forks | new"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict | None = Depends(optional_auth),
):
    """Browse the public research-graph archive from the CLI."""
    _require_public_route()
    user_id = user["user_id"] if user else None
    return await node_service.explore_public_graph_cards(
        db, user_id=user_id, title=query, sort=sort, page=page, per_page=per_page
    )


@router.get("/api/v1/researchers")
async def cli_list_researchers(
    query: str | None = Query(None, description="search by handle / name"),
    sort: str = Query("graphs", description="graphs | new"),
    page: int = Query(1, ge=1),
    per_page: int = Query(48, ge=1, le=100),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict | None = Depends(optional_auth),
):
    """Browse public researchers from the CLI."""
    _require_public_route()
    return await node_service.list_public_researchers(
        db, q=query, sort=sort, page=page, per_page=per_page
    )


@router.get("/api/v1/competitions")
async def cli_list_competitions(
    db: aiosqlite.Connection = Depends(get_db),
    user: dict | None = Depends(optional_auth),
):
    """Browse public competitions + leaders from the CLI."""
    _require_public_route()
    user_id = user["user_id"] if user else None
    return await competition_service.list_competition_cards(db, user_id=user_id)


@router.get("/api/v1/competitions/{slug}")
async def cli_get_competition(
    slug: str,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict | None = Depends(optional_auth),
):
    """One competition + its full leaderboard from the CLI."""
    _require_public_route()
    user_id = user["user_id"] if user else None
    result = await competition_service.get_competition_detail(db, slug, user_id=user_id)
    if not result:
        raise HTTPException(status_code=404, detail="Competition not found")
    return result
