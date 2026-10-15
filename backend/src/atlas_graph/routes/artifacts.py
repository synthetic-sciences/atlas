"""
Artifact routes -- upload, finalize, list, retrieve, annotate, and delete
artifacts attached to research nodes.
"""

from __future__ import annotations

import mimetypes

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from atlas_graph.auth.access_check import require_node_access
from atlas_graph.dependencies import get_current_user, get_db
from atlas_graph.models.artifact import (
    DeleteArtifactRequest,
    FinalizeUploadRequest,
    PrepareUploadRequest,
    SetArtifactNoteRequest,
)
from atlas_graph.services import artifact_service
from atlas_graph.storage.supabase_storage import storage

router = APIRouter()


from atlas_graph.routes._errors import service_error_to_http as _service_error_to_http


# ---- GET /api/artifacts/download/{path} -----------------------------------

@router.get("/api/artifacts/download/{path:path}")
async def download_artifact_blob(
    path: str,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Serve local artifact blobs returned by the storage fallback.

    Supabase-backed artifacts use signed URLs. Local development returns
    /api/artifacts/download/<storage_path>, so this route performs the same
    node ACL check before streaming bytes from the local storage client.
    """
    storage_path = path.lstrip("/")
    cursor = await db.execute(
        "SELECT node_id, title FROM artifacts WHERE storage_path = ?",
        (storage_path,),
    )
    raw = await cursor.fetchone()
    if raw is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="artifact not found")

    node_id, title = raw[0], raw[1]
    try:
        await require_node_access(db, user["user_id"], node_id, "view")
        data = await storage.download(storage_path)
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="blob not found")
    except ValueError as e:
        raise _service_error_to_http(e)

    media_type = mimetypes.guess_type(storage_path)[0] or "application/octet-stream"
    filename = title or storage_path.rsplit("/", 1)[-1]
    from atlas_graph.services.blob_serve import safe_blob_response

    # Inline preview for safe types; executable docs (html/svg/xml) are
    # neutralized + forced to download. XSS hardening.
    return safe_blob_response(content=data, media_type=media_type, filename=filename, inline=True)


# ---- GET /api/artifacts/{node_id} ----------------------------------------

@router.get("/api/artifacts/{node_id}")
async def list_artifacts(
    node_id: str,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await artifact_service.list_artifacts(db, user["user_id"], node_id)
    except ValueError as e:
        raise _service_error_to_http(e)


# ---- GET /api/artifacts/{node_id}/{artifact_id} --------------------------

@router.get("/api/artifacts/{node_id}/{artifact_id}")
async def get_artifact(
    node_id: str,
    artifact_id: str,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await artifact_service.get_artifact(
            db, user["user_id"], node_id, artifact_id
        )
    except ValueError as e:
        raise _service_error_to_http(e)


# ---- POST /api/artifacts/prepare ------------------------------------------

@router.post("/api/artifacts/prepare", status_code=status.HTTP_201_CREATED)
async def prepare_uploads(
    req: PrepareUploadRequest,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await artifact_service.prepare_uploads(db, user["user_id"], req)
    except ValueError as e:
        raise _service_error_to_http(e)


# ---- PUT /api/artifacts/upload/{upload_id} --------------------------------

@router.put("/api/artifacts/upload/{upload_id}")
async def handle_upload(
    upload_id: str,
    request: Request,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Accept raw file bytes for a prepared upload slot."""
    content_type = request.headers.get("content-type", "application/octet-stream")
    filename = request.headers.get("x-filename", "upload")
    data = await request.body()

    try:
        return await artifact_service.handle_upload(
            db, upload_id, content_type, filename, data
        )
    except ValueError as e:
        raise _service_error_to_http(e)


# ---- POST /api/artifacts/finalize -----------------------------------------

@router.post("/api/artifacts/finalize")
async def finalize_uploads(
    req: FinalizeUploadRequest,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await artifact_service.finalize_uploads(db, user["user_id"], req)
    except ValueError as e:
        raise _service_error_to_http(e)


# ---- PUT /api/artifacts/note ----------------------------------------------

@router.put("/api/artifacts/note")
async def set_artifact_note(
    req: SetArtifactNoteRequest,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await artifact_service.set_artifact_note(db, user["user_id"], req)
    except ValueError as e:
        raise _service_error_to_http(e)


# ---- DELETE /api/artifacts/{node_id}/{artifact_id} ------------------------

@router.delete(
    "/api/artifacts/{node_id}/{artifact_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_artifact(
    node_id: str,
    artifact_id: str,
    expected_revision: int | None = Query(None),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        req = DeleteArtifactRequest(
            node_id=node_id,
            artifact_id=artifact_id,
            expected_revision=expected_revision,
        )
        await artifact_service.delete_artifact(db, user["user_id"], req)
    except ValueError as e:
        raise _service_error_to_http(e)
