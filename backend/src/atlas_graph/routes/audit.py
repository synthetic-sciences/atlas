"""
Audit routes -- query audit events for a node.
"""

from __future__ import annotations

import aiosqlite
from fastapi import APIRouter, Depends, Query

from atlas_graph.dependencies import get_current_user, get_db
from atlas_graph.services import audit_service

router = APIRouter()


from atlas_graph.routes._errors import service_error_to_http as _service_error_to_http


# ---- GET /api/audit/{node_id} --------------------------------------------

@router.get("/api/audit/{node_id}")
async def list_events(
    node_id: str,
    limit: int = Query(50, ge=1, le=500),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Return audit events for a node, most recent first."""
    try:
        return await audit_service.list_events(db, user["user_id"], node_id, limit)
    except ValueError as e:
        raise _service_error_to_http(e)
