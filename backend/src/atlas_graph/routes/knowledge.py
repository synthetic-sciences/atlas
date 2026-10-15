"""Search caller-accessible graph chunks using an explicit query adapter."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from atlas_graph import config
from atlas_graph.dependencies import get_current_user, get_db
from atlas_graph.routes._errors import service_error_to_http
from atlas_graph.runtime import host
from atlas_graph.services import knowledge_router

router = APIRouter()


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=8192)
    mode: str = "hybrid"
    k: int = Field(10, ge=1, le=100)
    source_ids: list[str] = Field(default_factory=list)
    filters: dict = Field(default_factory=dict)
    include_graph: bool = True
    include_external: bool = False


@router.post("/api/knowledge/search")
async def search(
    body: SearchRequest,
    request: Request,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    query = host().query
    if query is None and config.MODE == "hosted":
        raise HTTPException(503, detail="The hosted query adapter is not configured")
    try:
        return await knowledge_router.unified_search(
            db, user["user_id"], query=body.query, mode=body.mode, k=body.k,
            source_ids=body.source_ids, filters=body.filters,
            include_graph=body.include_graph, include_external=body.include_external,
            embed=query(request).embed if query is not None else None,
        )
    except Exception as error:
        raise service_error_to_http(error)
