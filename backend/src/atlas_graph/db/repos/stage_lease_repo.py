from __future__ import annotations

from typing import Any


async def create_stage_lease(db, data: dict[str, Any]) -> None:
    await db.execute(
        """
        INSERT INTO stage_leases (
            stage_session_id, user_id, node_id, expected_revision, status,
            purpose, expires_at, released_at, release_reason, created_at,
            updated_at, heartbeat_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data["stage_session_id"],
            data["user_id"],
            data.get("node_id"),
            data.get("expected_revision"),
            data["status"],
            data.get("purpose"),
            data["expires_at"],
            data.get("released_at"),
            data.get("release_reason"),
            data["created_at"],
            data["updated_at"],
            data["heartbeat_at"],
        ),
    )


async def get_stage_lease(db, stage_session_id: str) -> dict | None:
    cursor = await db.execute(
        "SELECT * FROM stage_leases WHERE stage_session_id = ?",
        (stage_session_id,),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def update_stage_lease(db, stage_session_id: str, updates: dict[str, Any]) -> None:
    if not updates:
        return
    assignments = ", ".join(f"{key} = ?" for key in updates)
    await db.execute(
        f"UPDATE stage_leases SET {assignments} WHERE stage_session_id = ?",
        (*updates.values(), stage_session_id),
    )
