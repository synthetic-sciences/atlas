"""
Sharing routes -- manage node visibility and collaborator access.
"""

from __future__ import annotations

import aiosqlite
from fastapi import APIRouter, Depends, Path

from atlas_graph.dependencies import get_current_user, get_db
from atlas_graph.models.sharing import SetSharingBatchRequest, SetSharingRequest
from atlas_graph.services import sharing_service
from atlas_graph.services.sharing_service import CollaborationGatedError

router = APIRouter()

# Atlas node IDs are UUIDs on the wire. The path-param shape was previously
# unvalidated so things like ``../../../`` or empty strings reached the DB
# layer where they produced raw asyncpg / aiosqlite errors. A 422 here is
# friendlier and stops a class of "weird input crashes the route" issues.
_NODE_ID_PATTERN = (
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


from atlas_graph.routes._errors import service_error_to_http as _service_error_to_http


# ---- GET /api/sharing/{node_id} ------------------------------------------

@router.get("/api/sharing/{node_id}")
async def get_sharing(
    node_id: str = Path(..., pattern=_NODE_ID_PATTERN),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await sharing_service.get_sharing(db, user["user_id"], node_id)
    except (ValueError, CollaborationGatedError) as e:
        raise _service_error_to_http(e)


# ---- POST /api/sharing/{node_id} -----------------------------------------

@router.post("/api/sharing/{node_id}")
async def set_sharing(
    req: SetSharingRequest,
    node_id: str = Path(..., pattern=_NODE_ID_PATTERN),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await sharing_service.set_sharing(db, user["user_id"], node_id, req)
    except (ValueError, CollaborationGatedError) as e:
        raise _service_error_to_http(e)


# ---- POST /api/sharing/batch ---------------------------------------------

@router.post("/api/sharing/batch")
async def set_sharing_batch(
    req: SetSharingBatchRequest,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await sharing_service.set_sharing_batch(
            db, user["user_id"], req.node_ids, req
        )
    except (ValueError, CollaborationGatedError) as e:
        raise _service_error_to_http(e)
