"""
Tag management routes -- create, update, delete tags and manage assignments.
"""

from __future__ import annotations

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, status

from atlas_graph.dependencies import get_current_user, get_db
from atlas_graph.models.tag import TagAssignment, TagCreate, TagDelete, TagUpdate
from atlas_graph.services import tag_service

router = APIRouter()


from atlas_graph.routes._errors import service_error_to_http as _service_error_to_http


# ---- POST /api/tags -------------------------------------------------------

@router.post("/api/tags", status_code=status.HTTP_201_CREATED)
async def create_tag(
    req: TagCreate,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await tag_service.create_tag(db, user["user_id"], req)
    except ValueError as e:
        raise _service_error_to_http(e)


# ---- PUT /api/tags --------------------------------------------------------

@router.put("/api/tags")
async def update_tag(
    req: TagUpdate,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await tag_service.update_tag(db, user["user_id"], req)
    except ValueError as e:
        raise _service_error_to_http(e)


# ---- DELETE /api/tags -----------------------------------------------------

@router.delete("/api/tags", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_tag(
    req: TagDelete,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        await tag_service.delete_tag(db, user["user_id"], req)
    except ValueError as e:
        raise _service_error_to_http(e)


# ---- POST /api/tags/assignments -------------------------------------------

@router.post("/api/tags/assignments")
async def set_tag_assignments(
    req: TagAssignment,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await tag_service.set_tag_assignments(db, user["user_id"], req)
    except ValueError as e:
        raise _service_error_to_http(e)
