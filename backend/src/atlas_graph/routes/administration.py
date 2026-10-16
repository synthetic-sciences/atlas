"""Fixed graph operations; the host owns administrator identity and MFA policy."""

from datetime import datetime
import asyncio
import json
import os
import secrets
from uuid import UUID
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from atlas_graph import config
from atlas_graph.dependencies import get_db
from atlas_graph.services import administration
from atlas_graph.auth.access_check import check_node_access
from atlas_graph.services import research_log_service


def credential() -> str:
    token = os.environ.get("ATLAS_ADMIN_SERVICE_TOKEN", "").strip()
    other = {
        os.environ.get(name, "").strip()
        for name in (
            "ATLAS_ACCOUNT_SERVICE_TOKEN",
            "ATLAS_INDEX_SERVICE_TOKEN",
            "ATLAS_SIGNING_SECRET",
        )
    }
    if len(token) < 32 or token in other:
        raise RuntimeError(
            "Graph administration requires a separate service credential"
        )
    return token


async def authorize(request: Request) -> None:
    if config.MODE != "hosted":
        raise HTTPException(404, "Not found")
    try:
        token = credential()
    except RuntimeError:
        raise HTTPException(503, "Graph administration is not configured") from None
    if not secrets.compare_digest(token, request.headers.get("x-atlas-admin-key", "")):
        raise HTTPException(401, "Invalid graph administration credential")


router = APIRouter(
    prefix="/api/internal/host",
    dependencies=[Depends(authorize)],
    include_in_schema=False,
)


from atlas_graph.integrations.dashboard import Dashboard, Profile


@router.post("/identity-profile")
async def identity_profile(body: Profile, db=Depends(get_db)):
    await Dashboard.cache_profile(db, body)
    await db.commit()
    return {"synced": True}


class Access(BaseModel):
    actor: UUID
    node_id: UUID
    require: Literal["view", "write", "admin"] = "view"


class Mount(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actor: UUID
    project_id: UUID
    path: str = Field(min_length=8, max_length=512, pattern=r"^skills/[A-Za-z0-9._/-]+$")
    operation: Literal["put", "read", "remove"]
    markdown: str = Field(default="", max_length=524288)
    manifest: str = Field(default="", max_length=65536)


def mount_files(body: Mount) -> dict:
    from atlas_graph.fs.volume import _volume_root
    from atlas_graph.storage import local

    base = local.path(f"projects/{body.project_id}/{body.path}")
    root = _volume_root()
    if body.operation == "put":
        markdown, manifest = body.markdown.encode(), body.manifest.encode()
        if len(markdown) > 1_048_576 or len(manifest) > 65536:
            raise ValueError("Mounted skill exceeds the file limit")
        local.upload(f"{base}/SKILL.md", markdown, root=root)
        local.upload(f"{base}/skill.json", manifest, root=root)
    elif body.operation == "remove":
        # Remove only host-managed files; preserve any user-authored siblings.
        local.delete(f"{base}/SKILL.md", root=root)
        local.delete(f"{base}/skill.json", root=root)
    else:
        try:
            return {"body": local.download(f"{base}/SKILL.md", root=root, limit=524288).decode()}
        except FileNotFoundError:
            return {"body": ""}
    return {"path": f"{body.path}/SKILL.md"}


@router.post("/project-mount")
async def mount(body: Mount, db=Depends(get_db)):
    from atlas_graph.db.repos import node_repo

    root = await node_repo.find_root_node_id(db, str(body.project_id))
    if root != str(body.project_id):
        raise HTTPException(404, "Project not found")
    if await check_node_access(db, str(body.actor), root, "view" if body.operation == "read" else "write") is not True:
        raise HTTPException(403, "Access denied")
    try:
        return await asyncio.to_thread(mount_files, body)
    except (ValueError, UnicodeError):
        raise HTTPException(422, "Invalid project mount") from None


@router.post("/graph-access")
async def access(body: Access, db=Depends(get_db)):
    return {
        "allowed": await check_node_access(
            db, str(body.actor), str(body.node_id), body.require
        )
    }


class Log(BaseModel):
    actor: UUID
    project_id: UUID
    entry_type: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=300)
    body: str | None = Field(None, max_length=1_048_576)
    refs: list[dict] = Field(default_factory=list, max_length=100)


@router.post("/research-log")
async def log(body: Log, db=Depends(get_db)):
    if (
        await check_node_access(db, str(body.actor), str(body.project_id), "write")
        is not True
    ):
        return {"appended": False}
    entry = await research_log_service.append(
        db,
        project_id=str(body.project_id),
        entry_type=body.entry_type,
        title=body.title,
        body=body.body,
        refs=body.refs,
        created_by=str(body.actor),
    )
    return {"appended": True, "entry": entry}


@router.get("/summary")
async def summary(since: datetime, db=Depends(get_db)):
    return await administration.summary(db, since=since)


class Owners(BaseModel):
    user_ids: list[UUID] = Field(max_length=100)


@router.post("/owners")
async def owners(body: Owners, db=Depends(get_db)):
    return await administration.owners(db, [str(value) for value in body.user_ids])


class Filters(BaseModel):
    tag_id: UUID | None = None
    kind: str | None = Field(None, max_length=128)
    owner_user_id: UUID | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None
    cursor: int | None = Field(None, ge=0)
    page_size: int = Field(50, ge=1, le=200)

    def arguments(self) -> dict:
        values = self.model_dump(mode="json")
        values["cursor"] = str(self.cursor) if self.cursor is not None else None
        return values


@router.post("/graphs")
async def graphs(body: Filters, db=Depends(get_db)):
    return await administration.roots(db, **body.arguments())


@router.post("/audit/purge")
async def purge(
    days: int = Query(90, ge=7, le=3650), dry_run: bool = False, db=Depends(get_db)
):
    return await administration.purge(db, days=days, dry_run=dry_run)


@router.get("/graphs/{node_id}/export")
async def export(
    node_id: UUID,
    actor: UUID,
    max_nodes: int | None = Query(None, ge=1),
    db=Depends(get_db),
):
    return await administration.export(
        db, actor=str(actor), node_id=str(node_id), max_nodes=max_nodes
    )


@router.post("/graphs/export-stream")
async def stream(
    body: Filters,
    actor: UUID,
    max_nodes: int | None = Query(None, ge=1),
    db=Depends(get_db),
):
    listed = await administration.roots(db, **body.arguments())

    async def lines():
        for graph in listed["items"]:
            record = await administration.export(
                db, actor=str(actor), node_id=graph["node_id"], max_nodes=max_nodes
            )
            yield (json.dumps(record, separators=(",", ":")) + "\n").encode()

    return StreamingResponse(lines(), media_type="application/x-ndjson")
