"""Fixed graph operations; the host owns administrator identity and MFA policy."""

from datetime import datetime
import json
import os
import secrets
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from atlas_graph import config
from atlas_graph.dependencies import get_db
from atlas_graph.services import administration


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
