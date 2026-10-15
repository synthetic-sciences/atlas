"""
Artifact service -- prepare uploads, handle raw file uploads, finalize
batches, and manage artifact metadata.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import Any

from atlas_graph.auth.access_check import require_node_access
from atlas_graph.config import BATCH_TOKEN_TTL_SECONDS, MAX_UPLOAD_BYTES, SERVER_URL
from atlas_graph.db.repos import edge_repo, node_repo
from atlas_graph.storage.supabase_storage import storage
from atlas_graph.storage.url_signer import _b64url_encode


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _json_list(value: Any) -> list:
    if isinstance(value, str):
        return json.loads(value)
    return value or []


_ALLOWED_ARTIFACT_TYPES = {
    "text",
    "table",
    "json",
    "image",
    "banner",
    "html",
    "plotly_html",
    "vega",
    "checkpoint",
    "binary",
    "diff_carousel",
}


def _item_attr(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _coerce_artifact_type(value: Any) -> str:
    artifact_type = value.value if hasattr(value, "value") else value
    if not isinstance(artifact_type, str) or not artifact_type.strip():
        raise ValueError("Upload item artifact_type is required")
    artifact_type = artifact_type.strip()
    if artifact_type not in _ALLOWED_ARTIFACT_TYPES:
        raise ValueError(f"Unsupported artifact_type: {artifact_type}")
    return artifact_type


def _validate_upload_item(item: Any) -> dict[str, Any]:
    artifact_type = _coerce_artifact_type(_item_attr(item, "artifact_type"))

    filename = _item_attr(item, "filename")
    if not isinstance(filename, str) or not filename.strip():
        raise ValueError("Upload item filename is required")
    filename = filename.strip()

    media_type = _item_attr(item, "media_type", "application/octet-stream")
    if not isinstance(media_type, str) or not media_type.strip():
        raise ValueError("Upload item media_type is required")
    media_type = media_type.strip()

    metadata = _item_attr(item, "metadata", {})
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise ValueError("Upload item metadata must be an object")

    title = _item_attr(item, "title")
    note = _item_attr(item, "note")
    execution_id = _item_attr(item, "execution_id")

    return {
        "artifact_type": artifact_type,
        "filename": filename,
        "media_type": media_type,
        "title": title if isinstance(title, str) and title else filename,
        "note": note,
        "metadata": metadata,
        "execution_id": execution_id,
    }


async def _require_node_revision(
    db,
    node_id: str,
    expected_revision: int | None,
) -> dict:
    row = await node_repo.get_node(db, node_id)
    if row is None:
        raise ValueError(f"Node {node_id} not found")
    if expected_revision is not None and int(row["revision"]) != int(expected_revision):
        raise ValueError(
            f"409 conflict: expected revision {expected_revision}, current is {row['revision']}"
        )
    return row


async def _bump_node_revision(db, node_id: str, current_revision: int) -> int:
    now = _now()
    new_revision = int(current_revision) + 1
    await db.execute(
        "UPDATE nodes SET revision = ?, updated_at = ? WHERE node_id = ?",
        (new_revision, now, node_id),
    )
    return new_revision


# ---------------------------------------------------------------------------
# prepare_uploads
# ---------------------------------------------------------------------------

async def prepare_uploads(db, user_id: str, req) -> dict:
    """
    Prepare an upload batch.

    Generates a batch_token, stores metadata in artifact_upload_batches,
    and returns ticket-signed Atlas REST upload URLs for each item.
    """
    await require_node_access(db, user_id, req.node_id, "write")

    await _require_node_revision(db, req.node_id, req.expected_revision)
    if not req.items:
        raise ValueError("At least one upload item is required")

    now_dt = datetime.utcnow()
    now = now_dt.isoformat() + "Z"
    expires_at = (now_dt + timedelta(seconds=BATCH_TOKEN_TTL_SECONDS)).isoformat() + "Z"

    batch_token = str(uuid.uuid4())

    # Build items metadata with upload IDs
    items_meta: list[dict[str, Any]] = []
    response_items: list[dict[str, Any]] = []

    for raw_item in req.items:
        item = _validate_upload_item(raw_item)
        upload_id = str(uuid.uuid4())
        artifact_id = str(uuid.uuid4())

        item_meta = {
            "upload_id": upload_id,
            "artifact_id": artifact_id,
            "artifact_type": item["artifact_type"],
            "filename": item["filename"],
            "media_type": item["media_type"],
            "title": item["title"],
            "note": item["note"],
            "metadata": item["metadata"],
            "execution_id": item["execution_id"],
        }
        items_meta.append(item_meta)

        # Generate a signed ticket JWT for this upload
        ticket_jwt = _sign_upload_ticket(
            upload_id=upload_id,
            node_id=req.node_id,
            batch_token=batch_token,
            content_type=item["media_type"],
            ttl_seconds=BATCH_TOKEN_TTL_SECONDS,
        )
        upload_url = f"{SERVER_URL}/api/v1/artifacts/uploads/{upload_id}?ticket=v1:{ticket_jwt}"

        filename = item["filename"]
        media_type = item["media_type"]

        response_items.append({
            "upload_id": upload_id,
            "artifact_id": artifact_id,
            "upload_url": upload_url,
            "method": "PUT",
            "headers": {
                "Content-Type": media_type,
                "X-Thesis-Artifact-Filename": filename,
            },
            "curl_command": (
                f'curl -X PUT "{upload_url}" '
                f'-H "Content-Type: {media_type}" '
                f'-H "X-Thesis-Artifact-Filename: {filename}" '
                f'--data-binary @{filename}'
            ),
        })

    # Store batch in DB
    await db.execute(
        """INSERT INTO artifact_upload_batches
           (batch_token, node_id, expected_revision, items, expires_at, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (batch_token, req.node_id, req.expected_revision,
         json.dumps(items_meta), expires_at, now),
    )
    await db.commit()

    return {
        "batch_token": batch_token,
        "expires_at": expires_at,
        "max_upload_bytes": MAX_UPLOAD_BYTES,
        "items": response_items,
    }


def _sign_upload_ticket(
    upload_id: str,
    node_id: str,
    batch_token: str,
    content_type: str,
    ttl_seconds: int,
) -> str:
    """Create a signed JWT ticket for a single upload slot.

    Claims: upload_id, node_id, batch_token, content_type, iat, exp.
    Signed with SUPABASE_JWT_SECRET (HS256).
    """
    import hashlib
    import hmac
    import time as _time

    from atlas_graph import config as _cfg

    now = int(_time.time())
    payload = {
        "upload_id": upload_id,
        "node_id": node_id,
        "batch_token": batch_token,
        "content_type": content_type,
        "iat": now,
        "exp": now + ttl_seconds,
    }

    header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = _b64url_encode(json.dumps(payload).encode())
    signing_input = f"{header}.{body}".encode()
    sig = _b64url_encode(
        hmac.new(
            _cfg.SUPABASE_JWT_SECRET.encode(),
            signing_input,
            hashlib.sha256,
        ).digest()
    )
    return f"{header}.{body}.{sig}"


# ---------------------------------------------------------------------------
# handle_upload
# ---------------------------------------------------------------------------

async def handle_upload(
    db, upload_id: str, content_type: str, filename: str, data: bytes
) -> dict:
    """
    Handle the raw file upload for a single artifact.

    Writes bytes to DATA_DIR/blobs/artifacts/nodes/{node_id}/{artifact_id}.ext
    """
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError(f"Upload exceeds maximum size of {MAX_UPLOAD_BYTES} bytes")

    # Locate the batch holding this upload_id WITHOUT scanning the entire
    # ``artifact_upload_batches`` table on every PUT. Two paths:
    #  * Postgres uses JSONB containment (``items @> '[{"upload_id":"x"}]'``)
    #    which the existing GIN index ``idx_upload_batches_items_gin``
    #    accelerates to an index seek.
    #  * SQLite falls back to a substring LIKE on the JSON text - still a
    #    table scan in dev, but dev tables are small and this code path
    #    isn't on the prod hot loop.
    from atlas_graph import config
    target_batch_token = None
    target_node_id = None
    target_item = None
    if config.USE_POSTGRES:
        # @> requires a JSON literal; render it via json.dumps to escape
        # safely. asyncpg JSONB cast happens via the column type.
        needle = json.dumps([{"upload_id": upload_id}])
        cursor = await db.execute(
            "SELECT batch_token, node_id, items FROM artifact_upload_batches "
            "WHERE items @> ?::jsonb LIMIT 1",
            (needle,),
        )
    else:
        # SQLite: literal-substring filter narrows from "scan all rows" to
        # "scan only batches whose serialized items contains the upload_id".
        # Quote-anchored so e.g. upload_id "abc" doesn't match "abcdef".
        cursor = await db.execute(
            "SELECT batch_token, node_id, items FROM artifact_upload_batches "
            "WHERE items LIKE ? LIMIT 1",
            (f'%"upload_id": "{upload_id}"%',),
        )
    batch_row = await cursor.fetchone()

    if batch_row is not None:
        b_token, b_node_id, items_json = batch_row
        items = _json_list(items_json)
        for item in items:
            if item["upload_id"] == upload_id:
                target_batch_token = b_token
                target_node_id = b_node_id
                target_item = item
                break

    if target_item is None:
        raise ValueError(f"Upload ID {upload_id} not found in any batch")

    artifact_id = target_item["artifact_id"]
    original_filename = target_item["filename"]

    # Determine file extension
    ext = ""
    if "." in original_filename:
        ext = "." + original_filename.rsplit(".", 1)[-1]

    # Upload via storage client (Supabase or local fallback)
    relative_path = f"artifacts/nodes/{target_node_id}/{artifact_id}{ext}"
    await storage.upload(relative_path, data, content_type)
    blob_path = relative_path

    # Update the item metadata with storage_path
    cursor = await db.execute(
        "SELECT items FROM artifact_upload_batches WHERE batch_token = ?",
        (target_batch_token,),
    )
    raw = await cursor.fetchone()
    items = _json_list(raw[0])

    for item in items:
        if item["upload_id"] == upload_id:
            item["storage_path"] = blob_path
            item["uploaded"] = True
            break

    await db.execute(
        "UPDATE artifact_upload_batches SET items = ? WHERE batch_token = ?",
        (json.dumps(items), target_batch_token),
    )
    await db.commit()

    return {
        "upload_id": upload_id,
        "artifact_id": artifact_id,
        "status": "uploaded",
        "storage_path": blob_path,
        "bytes_written": len(data),
    }


# ---------------------------------------------------------------------------
# finalize_uploads
# ---------------------------------------------------------------------------

async def finalize_uploads(db, user_id: str, req) -> dict:
    """
    Finalize an upload batch: create artifact records, bump node revision once,
    and delete the batch record.
    """
    cursor = await db.execute(
        "SELECT * FROM artifact_upload_batches WHERE batch_token = ?",
        (req.batch_token,),
    )
    columns = [desc[0] for desc in cursor.description]
    raw = await cursor.fetchone()
    if raw is None:
        raise ValueError(f"Batch token {req.batch_token} not found")
    batch = dict(zip(columns, raw))

    node_id = batch["node_id"]
    if getattr(req, "node_id", None) is not None and req.node_id != node_id:
        raise ValueError(f"Batch token {req.batch_token} belongs to node {node_id}, not {req.node_id}")

    await require_node_access(db, user_id, node_id, "write")
    items = _json_list(batch["items"])
    now = _now()
    expected_revision = getattr(req, "expected_revision", None)
    if expected_revision is None:
        expected_revision = batch.get("expected_revision")
    node_row = await _require_node_revision(db, node_id, expected_revision)

    # Create artifact records
    for item in items:
        if not item.get("uploaded"):
            raise ValueError(f"Upload item {item.get('upload_id')} has not been uploaded")
        artifact_id = item["artifact_id"]
        storage_path = item.get("storage_path", "")
        payload: dict[str, str] = {}
        if storage_path:
            payload["storage_path"] = storage_path

        await db.execute(
            """INSERT INTO artifacts
               (artifact_id, node_id, artifact_type, title, note, payload,
                metadata, execution_id, storage_path, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                artifact_id,
                node_id,
                item["artifact_type"],
                item.get("title", item.get("filename", "")),
                item.get("note"),
                json.dumps(payload),
                json.dumps(item.get("metadata", {})),
                item.get("execution_id"),
                storage_path,
                now,
            ),
        )

    # Single revision bump for the entire batch
    await _bump_node_revision(db, node_id, int(node_row["revision"]))

    # Delete batch record
    await db.execute(
        "DELETE FROM artifact_upload_batches WHERE batch_token = ?",
        (req.batch_token,),
    )

    await db.commit()

    # Return full node response
    from atlas_graph.services.node_service import _full_node_response
    return await _full_node_response(db, node_id)


# ---------------------------------------------------------------------------
# list_artifacts
# ---------------------------------------------------------------------------

def _resolve_storage_url(row: dict) -> str | None:
    """Best URL to fetch an artifact's bytes from the frontend.

    Uploaded artifacts use either a durable storage URL or a relative storage
    path that the generic storage client can sign. Legacy hosted-agent blob
    URLs and absolute sandbox paths are intentionally not exposed.
    """
    db_url = row.get("storage_url")
    if db_url and not str(db_url).startswith("/api/agent/"):
        return db_url
    sp = row.get("storage_path")
    if sp and not str(sp).startswith("/"):
        return storage.get_signed_url(sp)
    return None


async def list_artifacts(db, user_id: str, node_id: str) -> list[dict]:
    """List all artifacts for a node."""
    await require_node_access(db, user_id, node_id, "view")

    cursor = await db.execute(
        "SELECT * FROM artifacts WHERE node_id = ? ORDER BY created_at",
        (node_id,),
    )
    columns = [desc[0] for desc in cursor.description]
    rows = [dict(zip(columns, r)) for r in await cursor.fetchall()]

    result = []
    for row in rows:
        payload = row.get("payload", "{}")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (json.JSONDecodeError, TypeError):
                payload = {}

        metadata = row.get("metadata", "{}")
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except (json.JSONDecodeError, TypeError):
                metadata = {}

        result.append({
            "artifact_id": row["artifact_id"],
            "artifact_type": row["artifact_type"],
            "title": row["title"],
            "note": row.get("note"),
            "payload": payload,
            "metadata": metadata,
            "execution_id": row.get("execution_id"),
            "storage_path": row.get("storage_path", ""),
            "storage_url": _resolve_storage_url(row),
            "volume_path": row.get("volume_path"),
            "created_at": row.get("created_at", ""),
        })

    return result


# ---------------------------------------------------------------------------
# get_artifact
# ---------------------------------------------------------------------------

async def get_artifact(
    db, user_id: str, node_id: str, artifact_id: str
) -> dict:
    """Get a single artifact with a storage_url."""
    await require_node_access(db, user_id, node_id, "view")

    cursor = await db.execute(
        "SELECT * FROM artifacts WHERE artifact_id = ? AND node_id = ?",
        (artifact_id, node_id),
    )
    columns = [desc[0] for desc in cursor.description]
    raw = await cursor.fetchone()
    if raw is None:
        raise ValueError(f"Artifact {artifact_id} not found for node {node_id}")
    row = dict(zip(columns, raw))

    payload = row.get("payload", "{}")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            payload = {}

    metadata = row.get("metadata", "{}")
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except (json.JSONDecodeError, TypeError):
            metadata = {}

    storage_path = row.get("storage_path", "")

    return {
        "artifact_id": row["artifact_id"],
        "artifact_type": row["artifact_type"],
        "title": row["title"],
        "note": row.get("note"),
        "payload": payload,
        "metadata": metadata,
        "execution_id": row.get("execution_id"),
        "storage_path": storage_path,
        "storage_url": _resolve_storage_url(row),
        "volume_path": row.get("volume_path"),
        "created_at": row.get("created_at", ""),
    }


# ---------------------------------------------------------------------------
# set_artifact_note
# ---------------------------------------------------------------------------

async def set_artifact_note(db, user_id: str, req) -> dict:
    """Update the note on an artifact."""
    await require_node_access(db, user_id, req.node_id, "write")
    node_row = await _require_node_revision(
        db, req.node_id, getattr(req, "expected_revision", None)
    )

    cursor = await db.execute(
        "SELECT artifact_id FROM artifacts WHERE artifact_id = ? AND node_id = ?",
        (req.artifact_id, req.node_id),
    )
    if await cursor.fetchone() is None:
        raise ValueError(f"Artifact {req.artifact_id} not found for node {req.node_id}")

    await db.execute(
        "UPDATE artifacts SET note = ? WHERE artifact_id = ? AND node_id = ?",
        (req.note, req.artifact_id, req.node_id),
    )
    new_revision = await _bump_node_revision(db, req.node_id, int(node_row["revision"]))
    await db.commit()
    artifact = await get_artifact(db, user_id, req.node_id, req.artifact_id)
    artifact["node_revision"] = new_revision
    return artifact


# ---------------------------------------------------------------------------
# delete_artifact
# ---------------------------------------------------------------------------

async def _delete_artifacts_for_node(
    db,
    node_id: str,
    artifact_ids: list[str],
) -> list[dict[str, str]]:
    if not artifact_ids:
        raise ValueError("At least one artifact_id is required")

    placeholders = ",".join("?" for _ in artifact_ids)
    cursor = await db.execute(
        f"""SELECT artifact_id, storage_path FROM artifacts
            WHERE node_id = ? AND artifact_id IN ({placeholders})""",
        [node_id, *artifact_ids],
    )
    rows = await cursor.fetchall()
    found = {
        row["artifact_id"] if hasattr(row, "keys") else row[0]: (
            row["storage_path"] if hasattr(row, "keys") else row[1]
        )
        for row in rows
    }
    missing = [artifact_id for artifact_id in artifact_ids if artifact_id not in found]
    if missing:
        raise ValueError(f"Artifacts not found for node {node_id}: {missing}")

    await db.execute(
        f"DELETE FROM artifacts WHERE node_id = ? AND artifact_id IN ({placeholders})",
        [node_id, *artifact_ids],
    )

    return [
        {"artifact_id": artifact_id, "storage_path": found.get(artifact_id) or ""}
        for artifact_id in artifact_ids
    ]


async def delete_artifact(db, user_id: str, req) -> dict:
    """Delete an artifact record and its blob (if any)."""
    await require_node_access(db, user_id, req.node_id, "write")
    node_row = await _require_node_revision(
        db, req.node_id, getattr(req, "expected_revision", None)
    )

    deleted = await _delete_artifacts_for_node(db, req.node_id, [req.artifact_id])
    new_revision = await _bump_node_revision(db, req.node_id, int(node_row["revision"]))
    await db.commit()

    for item in deleted:
        storage_path = item.get("storage_path")
        if not storage_path:
            continue
        try:
            await storage.delete(storage_path)
        except Exception:
            pass  # file may already be gone

    return {
        "deleted": True,
        "artifact_id": req.artifact_id,
        "deleted_count": 1,
        "node_revision": new_revision,
    }


async def delete_artifacts_bulk(db, user_id: str, req) -> dict:
    """Delete multiple artifact records for one node and bump its revision once."""
    if not getattr(req, "yes", False):
        raise ValueError("Bulk artifact deletion requires yes=true")

    artifact_ids = list(dict.fromkeys(getattr(req, "artifact_ids", []) or []))
    await require_node_access(db, user_id, req.node_id, "write")
    node_row = await _require_node_revision(db, req.node_id, req.expected_revision)

    deleted = await _delete_artifacts_for_node(db, req.node_id, artifact_ids)
    new_revision = await _bump_node_revision(db, req.node_id, int(node_row["revision"]))
    await db.commit()

    for item in deleted:
        storage_path = item.get("storage_path")
        if not storage_path:
            continue
        try:
            await storage.delete(storage_path)
        except Exception:
            pass

    return {
        "deleted": True,
        "deleted_count": len(deleted),
        "artifact_ids": [item["artifact_id"] for item in deleted],
        "node_revision": new_revision,
    }


async def list_files(
    db,
    user_id: str,
    node_id: str,
    include_descendants: bool = False,
    max_nodes: int = 200,
) -> dict:
    """List file-backed artifacts for a node, optionally including descendants."""
    if max_nodes < 1:
        raise ValueError("max_nodes must be at least 1")

    await require_node_access(db, user_id, node_id, "view")

    node_ids = [node_id]
    if include_descendants:
        seen = {node_id}
        queue = [node_id]
        while queue:
            current = queue.pop(0)
            for child_id in await edge_repo.get_children(db, current):
                if child_id in seen:
                    continue
                seen.add(child_id)
                node_ids.append(child_id)
                if len(node_ids) > max_nodes:
                    raise ValueError(f"list_files exceeded max_nodes={max_nodes}")
                queue.append(child_id)

    files: list[dict[str, Any]] = []
    for nid in node_ids:
        await require_node_access(db, user_id, nid, "view")
        for artifact in await list_artifacts(db, user_id, nid):
            storage_path = artifact.get("storage_path") or artifact.get("payload", {}).get("storage_path")
            if not storage_path:
                continue
            files.append({
                "file_id": artifact["artifact_id"],
                "artifact_id": artifact["artifact_id"],
                "node_id": nid,
                "filename": artifact.get("title") or storage_path.rsplit("/", 1)[-1],
                "artifact_type": artifact.get("artifact_type"),
                "media_type": artifact.get("metadata", {}).get("media_type"),
                "storage_path": storage_path,
                "storage_url": storage.get_signed_url(storage_path),
                "metadata": artifact.get("metadata", {}),
                "execution_id": artifact.get("execution_id"),
                "created_at": artifact.get("created_at", ""),
            })

    return {
        "files": files,
        "count": len(files),
        "node_count": len(node_ids),
    }
