"""Repository functions for the ``campaign_budgets`` table."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------------------
# Create
# ------------------------------------------------------------------

async def create_budget(
    db,
    *,
    budget_id: str,
    root_node_id: str,
    organizer_user_id: str,
    hard_cap_cents: int = 0,
    name: str | None = None,
    description: str | None = None,
    per_user_hard_cap_cents: int | None = None,
) -> dict[str, Any]:
    """Insert a new campaign budget and return it as a dict."""
    now = _now()
    budget_id = str(budget_id)
    root_node_id = str(root_node_id)
    organizer_user_id = str(organizer_user_id)
    await db.execute(
        """
        INSERT INTO campaign_budgets
            (budget_id, root_node_id, organizer_user_id,
             hard_cap_cents, spent_cents, status, name, description,
             per_user_hard_cap_cents, created_at, updated_at)
        VALUES (?, ?, ?, ?, 0, 'active', ?, ?, ?, ?, ?)
        """,
        (budget_id, root_node_id, organizer_user_id,
         hard_cap_cents, name, description, per_user_hard_cap_cents, now, now),
    )
    await db.commit()
    return {
        "budget_id": budget_id,
        "root_node_id": root_node_id,
        "organizer_user_id": organizer_user_id,
        "hard_cap_cents": hard_cap_cents,
        "spent_cents": 0,
        "status": "active",
        "name": name,
        "description": description,
        "per_user_hard_cap_cents": per_user_hard_cap_cents,
        "created_at": now,
        "updated_at": now,
    }


# ------------------------------------------------------------------
# Read
# ------------------------------------------------------------------

async def get_budget(db, budget_id: str) -> dict[str, Any] | None:
    """Fetch a single campaign budget by ID."""
    budget_id = str(budget_id)
    cursor = await db.execute(
        "SELECT * FROM campaign_budgets WHERE budget_id = ?",
        (budget_id,),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def list_budgets(db, root_node_id: str) -> list[dict[str, Any]]:
    """Return all campaign budgets for a root node, newest first."""
    root_node_id = str(root_node_id)
    cursor = await db.execute(
        "SELECT * FROM campaign_budgets WHERE root_node_id = ? ORDER BY created_at DESC",
        (root_node_id,),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------
# Update
# ------------------------------------------------------------------

async def update_budget(
    db,
    budget_id: str,
    *,
    hard_cap_cents: int | None = None,
    name: str | None = None,
    description: str | None = None,
    per_user_hard_cap_cents: int | None = None,
    status: str | None = None,
) -> dict[str, Any] | None:
    """Update a campaign budget's fields."""
    now = _now()
    budget_id = str(budget_id)
    sets: list[str] = ["updated_at = ?"]
    params: list[Any] = [now]

    if hard_cap_cents is not None:
        sets.append("hard_cap_cents = ?")
        params.append(hard_cap_cents)
    if name is not None:
        sets.append("name = ?")
        params.append(name)
    if description is not None:
        sets.append("description = ?")
        params.append(description)
    if per_user_hard_cap_cents is not None:
        sets.append("per_user_hard_cap_cents = ?")
        params.append(per_user_hard_cap_cents)
    if status is not None:
        sets.append("status = ?")
        params.append(status)

    params.append(budget_id)

    cursor = await db.execute(
        f"UPDATE campaign_budgets SET {', '.join(sets)} WHERE budget_id = ?",
        tuple(params),
    )
    await db.commit()
    if cursor.rowcount == 0:
        return None
    return await get_budget(db, budget_id)


# ------------------------------------------------------------------
# Revoke
# ------------------------------------------------------------------

async def revoke_budget(db, budget_id: str) -> dict[str, Any] | None:
    """Set a campaign budget's status to 'revoked'."""
    return await update_budget(db, budget_id, status="revoked")
