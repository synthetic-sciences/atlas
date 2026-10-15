from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from atlas_graph.auth.access_check import require_node_access
from atlas_graph.db.repos import node_repo, stage_lease_repo


def _now() -> datetime:
    return datetime.utcnow()


def _iso(ts: datetime) -> str:
    return ts.isoformat() + "Z"


async def acquire_stage_lease(
    db,
    user_id: str,
    *,
    node_id: str | None = None,
    expected_revision: int | None = None,
    stage_session_id: str | None = None,
    ttl_seconds: int = 1800,
    purpose: str | None = None,
) -> dict:
    if node_id:
        await require_node_access(db, user_id, node_id, "write")
        row = await node_repo.get_node(db, node_id)
        if row is None:
            raise ValueError(f"Node {node_id} not found")
        if expected_revision is not None and int(row["revision"]) != expected_revision:
            raise ValueError(
                f"409 conflict: expected revision {expected_revision}, current is {row['revision']}"
            )
        if expected_revision is None:
            expected_revision = int(row["revision"])

    now = _now()
    lease = {
        "stage_session_id": stage_session_id or str(uuid.uuid4()),
        "user_id": user_id,
        "node_id": node_id,
        "expected_revision": expected_revision,
        "status": "active",
        "purpose": purpose,
        "expires_at": _iso(now + timedelta(seconds=max(60, ttl_seconds))),
        "released_at": None,
        "release_reason": None,
        "created_at": _iso(now),
        "updated_at": _iso(now),
        "heartbeat_at": _iso(now),
    }
    await stage_lease_repo.create_stage_lease(db, lease)
    await db.commit()
    return lease


async def get_active_lease(db, user_id: str, stage_session_id: str) -> dict | None:
    lease = await stage_lease_repo.get_stage_lease(db, stage_session_id)
    if not lease:
        return None
    if lease["user_id"] != user_id:
        raise PermissionError("Stage lease does not belong to you.")
    if lease.get("status") != "active":
        return None
    return lease


async def heartbeat_stage_lease(
    db,
    user_id: str,
    stage_session_id: str,
    *,
    ttl_seconds: int = 1800,
) -> dict:
    lease = await stage_lease_repo.get_stage_lease(db, stage_session_id)
    if not lease:
        raise ValueError(f"Stage lease {stage_session_id} not found")
    if lease["user_id"] != user_id:
        raise PermissionError("Stage lease does not belong to you.")
    now = _now()
    updates = {
        "status": "active",
        "heartbeat_at": _iso(now),
        "updated_at": _iso(now),
        "expires_at": _iso(now + timedelta(seconds=max(60, ttl_seconds))),
    }
    await stage_lease_repo.update_stage_lease(db, stage_session_id, updates)
    await db.commit()
    lease.update(updates)
    return lease


async def release_stage_lease(
    db,
    user_id: str,
    stage_session_id: str,
    *,
    reason: str = "released",
) -> dict:
    lease = await stage_lease_repo.get_stage_lease(db, stage_session_id)
    if not lease:
        raise ValueError(f"Stage lease {stage_session_id} not found")
    if lease["user_id"] != user_id:
        raise PermissionError("Stage lease does not belong to you.")
    now = _now()
    updates = {
        "status": "released",
        "released_at": _iso(now),
        "release_reason": reason,
        "updated_at": _iso(now),
    }
    await stage_lease_repo.update_stage_lease(db, stage_session_id, updates)
    await db.commit()
    lease.update(updates)
    return lease
