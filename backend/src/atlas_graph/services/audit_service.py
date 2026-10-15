"""
Audit service -- log and query audit events for node operations.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from atlas_graph.auth.access_check import require_node_access


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


# ---------------------------------------------------------------------------
# log_event
# ---------------------------------------------------------------------------

async def log_event(
    db,
    actor_user_id: str,
    key_id: str,
    node_id: str,
    operation: str,
    idempotency_key: str,
    expected_revision: int | None,
    result_revision: int,
    request_hash: str,
) -> None:
    """
    Record an audit event.

    Parameters
    ----------
    db : aiosqlite.Connection
    actor_user_id : str
        The user who performed the action.
    key_id : str
        The API key (oauth_client_id) used for authentication.
    node_id : str
        The node affected.
    operation : str
        E.g. "stage_create", "commit_node", "delete_node".
    idempotency_key : str
        Client-supplied idempotency key.
    expected_revision : int | None
        The revision the client expected.
    result_revision : int
        The revision after the operation.
    request_hash : str
        Hash of the request body for dedup.
    """
    event_id = str(uuid.uuid4())
    now = _now()

    # Coerce revision fields to int; CLI wrappers may pass strings.
    if expected_revision is not None:
        expected_revision = int(expected_revision)
    result_revision = int(result_revision)

    # Keep the historical identifier shape for existing audit rows.
    oauth_client_id = f"mcp_api_key:{actor_user_id}:{key_id}"

    await db.execute(
        """INSERT INTO audit_events
           (event_id, actor_user_id, oauth_client_id, node_id, operation,
            idempotency_key, expected_revision, result_revision, request_hash,
            timestamp)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            event_id,
            actor_user_id,
            oauth_client_id,
            node_id,
            operation,
            idempotency_key,
            expected_revision,
            result_revision,
            request_hash,
            now,
        ),
    )
    await db.commit()

    # Knowledge v0: notify the background indexer for commit-shaped ops so
    # newly committed nodes get embedded.  Failures here must never affect
    # the audit log's primary responsibility.
    try:
        from atlas_graph.services.indexer_worker import notify_commit

        await notify_commit(operation, node_id)
    except Exception:  # pragma: no cover - defensive
        import logging

        logging.getLogger("indexer").exception(
            "notify_commit failed (op=%s node_id=%s)", operation, node_id
        )


# ---------------------------------------------------------------------------
# list_events
# ---------------------------------------------------------------------------

async def list_events(
    db, user_id: str, node_id: str, limit: int = 50
) -> list[dict]:
    """
    List audit events for a node, most recent first.

    Parameters
    ----------
    db : aiosqlite.Connection
    user_id : str
        The requesting user (for future access-control checks).
    node_id : str
        The node to query events for.
    limit : int
        Max events to return (default 50).

    Returns
    -------
    list[dict]
        List of AuditEvent-compatible dicts.
    """
    await require_node_access(db, user_id, node_id, "view")

    cursor = await db.execute(
        """SELECT event_id, actor_user_id, oauth_client_id, node_id,
                  operation, idempotency_key, expected_revision,
                  result_revision, request_hash, timestamp
           FROM audit_events
           WHERE node_id = ?
           ORDER BY timestamp DESC
           LIMIT ?""",
        (node_id, limit),
    )
    columns = [desc[0] for desc in cursor.description]
    rows = [dict(zip(columns, r)) for r in await cursor.fetchall()]

    return rows
