"""Public competition routes: directory + graph-backed leaderboards.

Read-only and public (optional_auth) so the Explore surface and the Atlas CLI
can browse competitions without a key, exactly like the researcher directory.
"""
from __future__ import annotations

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException

from atlas_graph.dependencies import get_db, optional_auth
from atlas_graph import config
from atlas_graph.services import competition_service

router = APIRouter()


def _require_public_route() -> None:
    if not config.PUBLIC_GRAPHS_ENABLED:
        raise HTTPException(status_code=404, detail="Not found")


@router.get("/api/competitions")
async def list_competitions(
    db: aiosqlite.Connection = Depends(get_db),
    user: dict | None = Depends(optional_auth),
):
    """Directory of public competitions with entry counts + current leaders."""
    _require_public_route()
    user_id = user["user_id"] if user else None
    return await competition_service.list_competition_cards(db, user_id=user_id)


@router.get("/api/competitions/{slug}")
async def get_competition(
    slug: str,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict | None = Depends(optional_auth),
):
    """One competition plus its full ranked leaderboard."""
    _require_public_route()
    user_id = user["user_id"] if user else None
    result = await competition_service.get_competition_detail(db, slug, user_id=user_id)
    if not result:
        raise HTTPException(status_code=404, detail="Competition not found")
    return result
