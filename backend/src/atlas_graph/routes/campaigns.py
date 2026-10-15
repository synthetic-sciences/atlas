"""
Campaign REST routes -- snapshot and budget listing for the web UI.

Endpoints:
    GET  /api/campaigns                     -- list campaign-configured roots
    GET  /api/campaigns/{node_id}/snapshot  -- campaign snapshot (tree metrics)
    GET  /api/campaigns/{node_id}/budgets   -- list budgets for a campaign root
    POST /api/campaigns/{node_id}/budgets   -- create a new budget
"""

from __future__ import annotations

import logging
import uuid

import aiosqlite
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from atlas_graph.auth.access_check import require_node_access
from atlas_graph.db.repos import campaign_repo
from atlas_graph.dependencies import get_current_user, get_db
from atlas_graph.services import campaign_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

from atlas_graph.routes._errors import service_error_to_http as _service_error_to_http


# ---------------------------------------------------------------------------
# GET /api/campaigns  (list campaign-configured roots only)
# ---------------------------------------------------------------------------

@router.get("")
async def list_campaigns(
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Return root nodes that are actual campaigns (have budgets or campaign_config artifacts).

    A node is campaign-configured if:
    1. It has any rows in campaign_budgets, OR
    2. It has an artifact with metadata containing campaign_role = 'config'
    """
    user_id = user["user_id"]
    # Find root node IDs that have campaign budgets
    cursor = await db.execute(
        """
        SELECT DISTINCT cb.root_node_id
        FROM campaign_budgets cb
        JOIN nodes n ON n.node_id = cb.root_node_id
        WHERE n.owner_user_id = ?
        """,
        (user_id,),
    )
    budget_rows = await cursor.fetchall()
    campaign_ids = {row[0] for row in budget_rows}

    # Also find roots with campaign_config artifacts
    cursor = await db.execute(
        """
        SELECT DISTINCT a.node_id
        FROM artifacts a
        JOIN nodes n ON n.node_id = a.node_id
        WHERE n.owner_user_id = ?
          AND a.metadata LIKE '%campaign_role%'
        """,
        (user_id,),
    )
    config_rows = await cursor.fetchall()
    for row in config_rows:
        campaign_ids.add(row[0])

    if not campaign_ids:
        return {"campaigns": []}

    # Single batched fetch instead of N+1 ``get_node`` round-trips.
    # Access is already constrained by the owner_user_id WHERE in the
    # discovery queries above, so ``require_node_access`` would be
    # redundant here. ``get_nodes_by_ids`` returns a {id: row} map; we
    # adapt to the topology projection shape callers expect.
    from atlas_graph.db.repos import node_repo, edge_repo
    from atlas_graph.services.node_service import _build_node_response

    rows_by_id = await node_repo.get_nodes_by_ids(db, list(campaign_ids))
    if not rows_by_id:
        return {"campaigns": []}
    parents_map, children_map = await edge_repo.get_edges_for_nodes(
        db, list(rows_by_id.keys()),
    )
    campaigns = []
    for nid, row in rows_by_id.items():
        node_dict = _build_node_response(
            row,
            parents_map.get(nid, []),
            children_map.get(nid, []),
        )
        node_dict["graph_projection"] = "topology"
        campaigns.append(node_dict)
    return {"campaigns": campaigns}


# ---------------------------------------------------------------------------
# GET /api/campaigns/{node_id}/snapshot
# ---------------------------------------------------------------------------

@router.get("/{node_id}/snapshot")
async def get_campaign_snapshot(
    node_id: str,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Return a full campaign snapshot for the tree rooted at *node_id*."""
    try:
        return await campaign_service.get_snapshot(db, user["user_id"], node_id)
    except ValueError as e:
        raise _service_error_to_http(e)


# ---------------------------------------------------------------------------
# GET /api/campaigns/{node_id}/budgets
# ---------------------------------------------------------------------------

@router.get("/{node_id}/budgets")
async def list_campaign_budgets(
    node_id: str,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """List all budgets for the campaign rooted at *node_id*."""
    try:
        await require_node_access(db, user["user_id"], node_id, "view")
    except ValueError as e:
        raise _service_error_to_http(e)

    budgets = await campaign_repo.list_budgets(db, node_id)
    return {"budgets": budgets}


# ---------------------------------------------------------------------------
# POST /api/campaigns/{node_id}/budgets
# ---------------------------------------------------------------------------

class CreateBudgetBody(BaseModel):
    hard_cap_cents: int = Field(..., description="Hard spending cap in cents.")
    name: str | None = Field(None, description="Optional human-readable name for the budget.")


@router.post("/{node_id}/budgets")
async def create_campaign_budget(
    node_id: str,
    body: CreateBudgetBody,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Create a new budget for the campaign rooted at *node_id*."""
    user_id = user["user_id"]
    try:
        await require_node_access(db, user_id, node_id, "admin")
    except ValueError as e:
        raise _service_error_to_http(e)

    budget_id = f"budget-{uuid.uuid4()}"
    result = await campaign_repo.create_budget(
        db,
        budget_id=budget_id,
        root_node_id=node_id,
        organizer_user_id=user_id,
        hard_cap_cents=body.hard_cap_cents,
    )
    return result
