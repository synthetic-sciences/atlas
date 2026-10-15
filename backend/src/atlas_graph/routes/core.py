"""Graph HTTP contract shared by the hosted adapter and standalone Atlas."""
from __future__ import annotations
import hashlib
import ipaddress
import json
import logging
import mimetypes
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Literal
from urllib.parse import parse_qs, urlencode, urlparse
from uuid import UUID
import aiosqlite
import httpx
from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool
from atlas_graph import config
from atlas_graph.auth.access_check import check_node_access, require_node_access
from atlas_graph.dependencies import get_current_user, get_db, optional_auth
from atlas_graph.models.artifact import DeleteArtifactRequest, FinalizeUploadRequest, PrepareUploadRequest, SetArtifactNoteRequest
from atlas_graph.models.node import AddParentRequest, BranchNodeRequest, CommitNodeRequest, MergeNodesRequest, RemoveParentRequest, StageNodeCreateRequest, StageNodeUpdateRequest
from atlas_graph.models.sharing import SetSharingBatchRequest, SetSharingRequest
from atlas_graph.models.tag import TagAssignment, TagCreate, TagDelete, TagUpdate
from atlas_graph.routes._errors import service_error_to_http as _service_error_to_http
from atlas_graph.services import artifact_service, audit_service, campaign_service, export_import_service, node_service, project_state_service, repo_state_service, research_log_service, sharing_service, stage_lease_service, tag_service
from atlas_graph.storage.supabase_storage import storage
from atlas_graph.storage.url_signer import verify_signed_token
router = APIRouter(tags=["atlas-graphs"])
logger = logging.getLogger(__name__)
def _now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"
@router.get("/projects")
async def cli_list_projects(
    dedupe_key: str | None = Query(None),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    return await project_state_service.list_projects(
        db,
        user_id=user["user_id"],
        dedupe_key=dedupe_key,
    )


@router.post("/projects", status_code=status.HTTP_201_CREATED)
async def cli_create_project(
    body: dict[str, Any] = Body(...),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    return await project_state_service.create_project(
        db,
        user_id=user["user_id"],
        title=str(body.get("title") or ""),
        repo_url=body.get("repo_url"),
        branch_name=body.get("branch_name"),
        dedupe_key=body.get("dedupe_key"),
    )


@router.post("/projects/merge")
async def cli_merge_projects(
    body: dict[str, Any] = Body(...),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    canonical_id = str(body.get("canonical_id") or "").strip()
    duplicate_ids = body.get("duplicate_ids")
    if not canonical_id:
        raise HTTPException(status_code=422, detail="canonical_id is required")
    if not isinstance(duplicate_ids, list) or not all(
        isinstance(item, str) and item.strip() for item in duplicate_ids
    ):
        raise HTTPException(
            status_code=422, detail="duplicate_ids must be a list of ids"
        )
    return await project_state_service.merge_projects(
        db,
        user_id=user["user_id"],
        canonical_id=canonical_id,
        duplicate_ids=[item.strip() for item in duplicate_ids],
    )


@router.post("/repos/{node_id}/pin")
async def cli_pin_project_repo(
    node_id: str,
    body: dict[str, Any] | None = Body(None),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Pin the exact code state recorded on a research-map node."""
    payload = body or {}
    return await repo_state_service.pin(
        db,
        user_id=user["user_id"],
        node_id=node_id,
        sha=payload.get("sha"),
        tag=payload.get("tag"),
    )


@router.post("/repos/{node_id}/capture")
async def cli_capture_project_repo(
    node_id: str,
    body: dict[str, Any] | None = Body(None),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Record caller-observed repository state and optionally pin it."""
    payload = body or {}
    return await repo_state_service.capture(
        db,
        user_id=user["user_id"],
        node_id=node_id,
        repo_url=payload.get("repo_url"),
        branch_name=payload.get("branch_name"),
        head_commit_sha=payload.get("head_commit_sha"),
        pin_commit=bool(payload.get("pin", False)),
        tag=payload.get("tag"),
    )


@router.get("/repos/{node_id}/verify")
async def cli_verify_project_repo(
    node_id: str,
    sha: str | None = Query(None),
    tag: str | None = Query(None),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    return await repo_state_service.verify(
        db,
        user_id=user["user_id"],
        node_id=node_id,
        sha=sha,
        tag=tag,
    )


def _body(value: dict[str, Any] | None) -> dict[str, Any]:
    return dict(value or {})




def _split_ids(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _split_strings(value: Any) -> list[str]:
    return _split_ids(value)


def _coerce_sharing_mode(value: Any) -> str | None:
    if value is None:
        return None
    raw = str(value).strip().lower()
    if raw == "link":
        return "unlisted"
    if raw == "account":
        return "private"
    return raw






def _request_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload if payload is not None else {}, sort_keys=True, default=str
        ).encode("utf-8")
    ).hexdigest()


async def _log_cli_audit(
    db: aiosqlite.Connection,
    user: dict,
    request: Request,
    *,
    node_id: str | None,
    operation: str,
    expected_revision: int | None,
    result_revision: int | None,
    payload: Any,
) -> None:
    if not node_id:
        return
    if result_revision is None:
        try:
            result_revision = await _current_revision(db, node_id)
        except Exception:
            result_revision = expected_revision or 0
    idempotency_key = (
        request.headers.get("Idempotency-Key")
        or request.headers.get("X-Idempotency-Key")
        or ""
    )
    if not idempotency_key:
        idempotency_key = f"atlas-rest-{_request_hash({'operation': operation, 'node_id': node_id, 'payload': payload})}"
    await audit_service.log_event(
        db,
        user["user_id"],
        user.get("key_id") or "direct-http",
        node_id,
        operation,
        idempotency_key,
        expected_revision,
        result_revision,
        _request_hash(payload),
    )


def _node_from_result(result: Any) -> dict[str, Any] | None:
    if isinstance(result, dict):
        node = result.get("node")
        if isinstance(node, dict):
            return node
        if result.get("node_id"):
            return result
    return None


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).replace("\r", " ").replace("\n", " ").split())


def _source_text(row: dict[str, Any]) -> str:
    return _clean_text(
        " ".join(
            part
            for part in (
                row.get("title"),
                row.get("summary"),
                row.get("content"),
            )
            if part
        )
    )


def _derive_hypothesis(row: dict[str, Any]) -> str:
    text = _source_text(row)
    title = _clean_text(row.get("title"))
    if text:
        sentence = text.split(". ", 1)[0].strip(" .")
        return f"{sentence}." if sentence else title
    return title or "The staged branch should clarify the research question."


def _derive_insights(row: dict[str, Any]) -> list[str]:
    text = _source_text(row)
    if not text:
        fallback = _clean_text(row.get("title"))
        return (
            [fallback]
            if fallback
            else ["Staged content has no extractable insight yet."]
        )
    raw_sentences: list[str] = []
    for chunk in text.replace("\n", " ").split("."):
        sentence = _clean_text(chunk)
        if len(sentence) >= 8:
            raw_sentences.append(sentence)
        if len(raw_sentences) >= 5:
            break
    if not raw_sentences:
        raw_sentences = [text[:240].strip()]
    return [
        sentence if sentence.endswith(".") else f"{sentence}."
        for sentence in raw_sentences
    ]


async def _current_revision(db: aiosqlite.Connection, node_id: str) -> int:
    from atlas_graph.db.repos import node_repo

    row = await node_repo.get_node(db, node_id)
    if row is None:
        raise ValueError(f"Node {node_id} not found")
    return int(row["revision"])


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _decode_payload_json(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("payload_json must be valid JSON") from exc
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("payload_json must decode to an object")


def _with_commit_defaults(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    normalized.setdefault("kind", "insight")
    normalized.setdefault("outcome", "completed")
    if "insights" not in normalized:
        fallback = (
            normalized.get("summary")
            or normalized.get("title")
            or "Committed via Atlas CLI"
        )
        normalized["insights"] = [fallback]
    return normalized


def _normalize_staged_payload(params: dict[str, Any]) -> dict[str, Any]:
    payload = dict(params.get("staged_payload") or {})
    repo_context: dict[str, Any] = {}
    nested_repo_context = payload.pop("repo_context", None)
    if isinstance(nested_repo_context, dict):
        repo_context.update(nested_repo_context)
    top_repo_context = params.get("repo_context") or {}
    if isinstance(top_repo_context, dict):
        repo_context.update(top_repo_context)
    for key in (
        "title",
        "summary",
        "content",
        "kind",
        "outcome",
        "hypothesis",
        "no_artifacts_reason",
        "insights",
        "updated_by",
        "repo_url",
        "branch_name",
        "head_commit_sha",
        "origin_host",
        "external_transcript_ref",
    ):
        if params.get(key) is not None and key not in payload:
            payload[key] = params[key]
    for key in (
        "repo_url",
        "branch_name",
        "head_commit_sha",
        "origin_host",
        "updated_by",
        "external_transcript_ref",
    ):
        if repo_context.get(key) is not None:
            payload.setdefault(key, repo_context[key])
    return {key: value for key, value in payload.items() if value is not None}


def _normalize_commit_new_params(params: dict[str, Any]) -> dict[str, Any]:
    envelope = _decode_payload_json(params.get("payload_json"))
    if not envelope:
        return dict(params)
    missing: list[str] = []
    for key in ("local_temp_node_id", "parent_ids", "staged_payload"):
        if key not in envelope:
            missing.append(key)
    staged = envelope.get("staged_payload")
    if not isinstance(staged, dict):
        missing.append("staged_payload")
    else:
        for key in ("title", "content", "summary"):
            if key not in staged:
                missing.append(f"staged_payload.{key}")
    if missing:
        raise ValueError(
            "payload_json missing required keys: " + ", ".join(dict.fromkeys(missing))
        )
    merged = {
        key: value
        for key, value in params.items()
        if key != "payload_json" and value is not None
    }
    merged.update(
        {
            key: value
            for key, value in envelope.items()
            if key != "staged_payload" and value is not None
        }
    )
    merged["staged_payload"] = {
        **_with_commit_defaults(dict(staged)),
        **dict(merged.get("staged_payload") or {}),
    }
    return merged


def _normalize_commit_params(params: dict[str, Any]) -> dict[str, Any]:
    envelope = _decode_payload_json(params.get("payload_json"))
    if not envelope:
        return {key: value for key, value in params.items() if key != "payload_json"}
    staged = envelope.get("staged_payload")
    if not isinstance(staged, dict):
        raise ValueError("payload_json.staged_payload must be an object")
    merged = {
        key: value
        for key, value in params.items()
        if key != "payload_json" and value is not None
    }
    for key in ("stage_session_id", "base_committed_revision", "repo_context"):
        if envelope.get(key) is not None and key not in merged:
            merged[key] = envelope[key]
    if merged.get("expected_revision") is None:
        merged["expected_revision"] = envelope.get("base_committed_revision")
    merged["staged_payload"] = _with_commit_defaults(
        {
            **dict(staged),
            **dict(merged.get("staged_payload") or {}),
        }
    )
    return merged


async def _commit_existing_node(
    db, user: dict[str, Any], params: dict[str, Any]
) -> dict:
    params = _normalize_commit_params(params)
    node_id = params["node_id"]
    lease_to_release = None
    if params.get("stage_session_id"):
        lease = await stage_lease_service.get_active_lease(
            db, user["user_id"], params["stage_session_id"]
        )
        if lease and lease.get("node_id") and lease["node_id"] != node_id:
            return {
                "error": "stage_session_node_mismatch",
                "message": "Stage session belongs to a different node.",
            }
        lease_to_release = lease

    staged_payload = _normalize_staged_payload(params)
    if staged_payload:
        expected = params.get("expected_revision")
        if expected is None:
            expected = await _current_revision(db, node_id)
        updated = await node_service.stage_update(
            db,
            user["user_id"],
            StageNodeUpdateRequest(
                node_id=node_id, expected_revision=expected, **staged_payload
            ),
        )
        params["expected_revision"] = updated["revision"]
    if params.get("expected_revision") is None:
        params["expected_revision"] = await _current_revision(db, node_id)

    result = await node_service.commit_node(
        db,
        user["user_id"],
        CommitNodeRequest(
            node_id=node_id,
            expected_revision=params["expected_revision"],
            summary=params.get("summary"),
        ),
    )
    if result is None:
        from atlas_graph.db.repos import node_repo
        from atlas_graph.services.node_service import (
            _full_node_response,
            _get_contract_warnings,
        )

        node_row = await node_repo.get_node(db, node_id)
        if node_row is None:
            return {"error": "commit_failed", "contract_warnings": [], "node": None}
        warnings = await _get_contract_warnings(db, node_row)
        if int(node_row["revision"]) != int(params["expected_revision"]):
            warnings.append(
                {
                    "code": "revision_mismatch",
                    "message": f"Expected revision {params['expected_revision']} but node is at revision {node_row['revision']}.",
                }
            )
        return {
            "error": "commit_failed",
            "contract_warnings": warnings,
            "node": await _full_node_response(db, node_id, user_id=user["user_id"]),
        }
    if lease_to_release:
        await stage_lease_service.release_stage_lease(
            db, user["user_id"], params["stage_session_id"], reason="committed"
        )
    return {"node": result}


async def _commit_new_node(db, user: dict[str, Any], params: dict[str, Any]) -> dict:
    params = _normalize_commit_new_params(params)
    payload = _normalize_staged_payload(params)
    create_payload = {
        "title": _first_present(payload.get("title"), params.get("title")),
        "summary": _first_present(payload.get("summary"), params.get("summary")),
        "content": _first_present(payload.get("content"), params.get("content")),
        "kind": _first_present(payload.get("kind"), params.get("kind"), "insight"),
        "hypothesis": _first_present(
            payload.get("hypothesis"), params.get("hypothesis")
        ),
        "parent_ids": params.get("parent_ids"),
        "repo_url": _first_present(payload.get("repo_url"), params.get("repo_url")),
        "branch_name": _first_present(
            payload.get("branch_name"), params.get("branch_name")
        ),
        "head_commit_sha": _first_present(
            payload.get("head_commit_sha"), params.get("head_commit_sha")
        ),
        "origin_host": _first_present(
            payload.get("origin_host"), params.get("origin_host")
        ),
        "updated_by": _first_present(
            payload.get("updated_by"), params.get("updated_by")
        ),
        "external_transcript_ref": _first_present(
            payload.get("external_transcript_ref"),
            params.get("external_transcript_ref"),
        ),
    }
    node = await node_service.stage_create(
        db,
        user["user_id"],
        StageNodeCreateRequest(
            **{key: value for key, value in create_payload.items() if value is not None}
        ),
    )
    update_payload = {
        key: value
        for key, value in {
            "outcome": payload.get("outcome") or params.get("outcome") or "completed",
            "no_artifacts_reason": _first_present(
                payload.get("no_artifacts_reason"), params.get("no_artifacts_reason")
            ),
            "insights": _first_present(
                payload.get("insights"),
                params.get("insights"),
                ["committed via Atlas CLI"],
            ),
        }.items()
        if value is not None
    }
    if update_payload:
        node = await node_service.stage_update(
            db,
            user["user_id"],
            StageNodeUpdateRequest(
                node_id=node["node_id"],
                expected_revision=node["revision"],
                **update_payload,
            ),
        )
    result = await node_service.commit_node(
        db,
        user["user_id"],
        CommitNodeRequest(
            node_id=node["node_id"],
            expected_revision=node["revision"],
            summary=_first_present(
                payload.get("summary"),
                params.get("summary"),
                node.get("summary"),
                node.get("title"),
                "Committed node",
            ),
        ),
    )
    if result is None:
        return {
            "error": "commit_new_node_failed",
            "node": node,
            "contract_warnings": node.get("contract_warnings", []),
        }
    return {
        "node": result,
        "local_temp_node_id": params.get("local_temp_node_id"),
        "stage_session_id": params.get("stage_session_id"),
        "committed_revision": result.get("revision"),
        "commit_required": False,
        "staged_changes_pending": False,
        "next_action_hint": "commit complete; no staged changes pending",
    }


def _looks_like_commit_new_envelope(body: dict[str, Any]) -> bool:
    return "staged_payload" in body and (
        "local_temp_node_id" in body or "parent_ids" in body
    )


def _looks_like_commit_envelope(body: dict[str, Any]) -> bool:
    return "staged_payload" in body and (
        "base_committed_revision" in body or "stage_session_id" in body
    )


def _jsonl_response(items: list[dict[str, Any]]) -> Response:
    content = "".join(json.dumps(item, separators=(",", ":")) + "\n" for item in items)
    return Response(content=content, media_type="application/x-ndjson")


async def _summary_markdown(db, user_id: str, node_ids: list[str]) -> str:
    sections: list[str] = []
    for node_id in node_ids:
        try:
            tree = await node_service.get_node_tree(
                db, user_id, node_id, projection="full", max_nodes=200
            )
        except ValueError:
            sections.append(f"## Node {node_id}\n\n_Node not found._\n")
            continue
        for node in tree.get("nodes", []):
            title = node.get("title") or node.get("slug_name") or node.get("node_id")
            meta = [
                f"kind={node.get('kind', 'untyped')}",
                f"lifecycle={node.get('lifecycle', 'staged')}",
            ]
            if node.get("outcome"):
                meta.append(f"outcome={node['outcome']}")
            block = f"## {title}\n\n_{' | '.join(meta)}_\n"
            if node.get("summary"):
                block += f"\n{node['summary']}\n"
            sections.append(block)
    return (
        "# Research Summary\n\n" + "\n---\n\n".join(sections)
        if sections
        else "# Research Summary\n\nNo nodes found.\n"
    )


def _safe_pdf_text(value: str) -> str:
    return value.encode("latin-1", "replace").decode("latin-1")


def _markdown_to_pdf(markdown: str, title: str = "Atlas Export") -> bytes:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_title(_safe_pdf_text(title))
    pdf.set_font("Helvetica", size=10)
    for raw_line in markdown.splitlines():
        line = _safe_pdf_text(raw_line)
        if line.startswith("### "):
            pdf.set_font("Helvetica", "B", 12)
            pdf.multi_cell(0, 8, line[4:])
            pdf.set_font("Helvetica", size=10)
        elif line.startswith("## "):
            pdf.set_font("Helvetica", "B", 14)
            pdf.multi_cell(0, 9, line[3:])
            pdf.set_font("Helvetica", size=10)
        elif line.startswith("# "):
            pdf.set_font("Helvetica", "B", 16)
            pdf.multi_cell(0, 10, line[2:])
            pdf.set_font("Helvetica", size=10)
        elif line.strip():
            pdf.multi_cell(0, 6, line)
        else:
            pdf.ln(3)
    output = pdf.output()
    if isinstance(output, bytes):
        return output
    if isinstance(output, bytearray):
        return bytes(output)
    return str(output).encode("latin-1", "replace")


def _pdf_response(pdf_bytes: bytes, filename: str = "atlas-summary.pdf") -> Response:
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )




def _public_request_base(request: Request) -> str:
    configured = (config.SERVER_URL or "").rstrip("/")
    if configured and "localhost" not in configured and "127.0.0.1" not in configured:
        return configured

    forwarded_proto = (
        (request.headers.get("x-forwarded-proto") or "").split(",", 1)[0].strip()
    )
    forwarded_host = (
        (request.headers.get("x-forwarded-host") or request.headers.get("host") or "")
        .split(",", 1)[0]
        .strip()
    )
    if forwarded_proto and forwarded_host:
        return f"{forwarded_proto}://{forwarded_host}".rstrip("/")

    return str(request.base_url).rstrip("/")


def _rewrite_upload_urls(result: dict[str, Any], request: Request) -> dict[str, Any]:
    rewritten = dict(result)
    items = []
    base = _public_request_base(request)
    for item in result.get("items") or []:
        next_item = dict(item)
        parsed = urlparse(str(item.get("upload_url") or ""))
        ticket = (parse_qs(parsed.query).get("ticket") or [""])[0]
        next_item["upload_url"] = (
            f"{base}/api/v1/artifacts/uploads/{item['upload_id']}?{urlencode({'ticket': ticket})}"
        )
        items.append(next_item)
    rewritten["items"] = items
    return rewritten


@router.get("/nodes/{node_id}/campaign/snapshot")
async def campaign_snapshot(
    node_id: str,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await campaign_service.get_snapshot(db, user["user_id"], node_id)
    except Exception as e:
        raise _service_error_to_http(e)


@router.get("/graph")
async def get_graph(
    node_id: str | None = Query(None),
    depth: int | None = Query(None),
    max_nodes: int | None = Query(None),
    page_size: int = Query(500, ge=1, le=10000),
    cursor: str | None = Query(None),
    filter_: str | None = Query(None, alias="filter"),
    exclude: str | None = Query(None),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await node_service.get_graph(
            db,
            user["user_id"],
            node_id=node_id,
            depth=depth,
            max_nodes=max_nodes,
            page_size=page_size,
            cursor=cursor,
            filters=filter_,
            exclude=exclude,
        )
    except Exception as e:
        raise _service_error_to_http(e)


@router.post("/nodes/commit-new", status_code=status.HTTP_201_CREATED)
async def commit_new_node(
    request: Request,
    body: dict[str, Any] | None = Body(None),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        payload = _body(body)
        params = (
            {"payload_json": payload}
            if _looks_like_commit_new_envelope(payload)
            else payload
        )
        result = await _commit_new_node(db, user, params)
        node = _node_from_result(result)
        if node and not result.get("error"):
            await _log_cli_audit(
                db,
                user,
                request,
                node_id=node.get("node_id"),
                operation="commit_new_node",
                expected_revision=None,
                result_revision=node.get("revision"),
                payload=payload,
            )
        return result
    except Exception as e:
        raise _service_error_to_http(e)


@router.post("/nodes/bulk-delete")
async def delete_nodes_bulk(
    request: Request,
    body: dict[str, Any] | None = Body(None),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        payload = _body(body)
        result = await node_service.bulk_delete_nodes(
            db,
            user["user_id"],
            _split_ids(payload.get("node_ids")),
            delete_mode=payload.get("delete_mode") or "detach_shared",
        )
        for deleted_id in result.get("deleted_node_ids") or []:
            await _log_cli_audit(
                db,
                user,
                request,
                node_id=deleted_id,
                operation="delete_nodes_bulk",
                expected_revision=None,
                result_revision=0,
                payload=payload,
            )
        return result
    except Exception as e:
        raise _service_error_to_http(e)


@router.post("/nodes/merge")
async def merge_nodes(
    request: Request,
    body: dict[str, Any] = Body(...),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        payload = _body(body)
        payload["node_ids"] = _split_ids(payload.get("node_ids"))
        req = MergeNodesRequest(**payload)
        node = await node_service.merge_nodes(db, user["user_id"], req)
        await _log_cli_audit(
            db,
            user,
            request,
            node_id=node.get("node_id"),
            operation="merge_nodes",
            expected_revision=None,
            result_revision=node.get("revision"),
            payload=payload,
        )
        return {"node": node}
    except Exception as e:
        raise _service_error_to_http(e)


@router.get("/nodes/resolve-by-slug")
async def resolve_slug(
    slug_name: str = Query(...),
    context_node_id: str | None = Query(None),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await node_service.resolve_node_slug(
            db, user["user_id"], slug_name, context_node_id=context_node_id
        )
    except Exception as e:
        raise _service_error_to_http(e)


@router.post("/nodes/access-policy/bulk")
async def set_sharing_bulk(
    body: dict[str, Any] = Body(...),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        payload = _body(body)
        node_ids = _split_ids(payload.get("node_ids"))
        req = SetSharingBatchRequest(
            node_ids=node_ids,
            sharing_mode=_coerce_sharing_mode(payload.get("sharing_mode")),
            collaborators=payload.get("collaborators"),
        )
        return {
            "items": await sharing_service.set_sharing_batch(
                db, user["user_id"], node_ids, req
            )
        }
    except Exception as e:
        raise _service_error_to_http(e)


@router.post("/nodes/access-policy/summaries")
async def sharing_summaries(
    body: dict[str, Any] = Body(...),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await sharing_service.get_sharing_summaries(
            db, user["user_id"], _split_ids(_body(body).get("node_ids"))
        )
    except Exception as e:
        raise _service_error_to_http(e)


@router.get("/nodes")
async def list_nodes(
    scope: Literal["owned_or_shared_private"] | None = Query(None),
    owners: str | None = Query(None),
    writers: str | None = Query(None),
    visibility: str | None = Query(None),
    kind: str | None = Query(None),
    lifecycle: str | None = Query(None),
    outcome: str | None = Query(None),
    root_only: bool | None = Query(None),
    repo_url: str | None = Query(None),
    tag_id: str | None = Query(None),
    title: str | None = Query(None),
    status_: str | None = Query(None, alias="status"),
    projection: str = Query("core"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await node_service.list_nodes(
            db,
            user["user_id"],
            scope=scope,
            owners=_split_ids(owners) or None,
            writers=_split_ids(writers) or None,
            visibility=visibility,
            kind=kind,
            lifecycle=lifecycle or status_,
            outcome=outcome,
            root_only=root_only,
            repo_url=repo_url,
            tag_id=tag_id,
            title=title,
            projection=projection,
            page=page,
            per_page=page_size,
        )
    except Exception as e:
        raise _service_error_to_http(e)


@router.post("/nodes")
async def create_node(
    request: Request,
    body: dict[str, Any] = Body(...),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        payload = _body(body)
        title = payload.get("title")
        if not title:
            raise ValueError("title is required")
        node = await node_service.stage_create(
            db,
            user["user_id"],
            StageNodeCreateRequest(
                title=title, summary=title, content="", kind="insight"
            ),
        )
        node = await node_service.stage_update(
            db,
            user["user_id"],
            StageNodeUpdateRequest(
                node_id=node["node_id"],
                expected_revision=node["revision"],
                outcome="completed",
                insights=[title],
            ),
        )
        committed = await node_service.commit_node(
            db,
            user["user_id"],
            CommitNodeRequest(
                node_id=node["node_id"],
                expected_revision=node["revision"],
                summary=title,
            ),
        )
        if committed is None:
            raise ValueError("failed to commit node")
        await _log_cli_audit(
            db,
            user,
            request,
            node_id=committed.get("node_id"),
            operation="create_node",
            expected_revision=None,
            result_revision=committed.get("revision"),
            payload=payload,
        )
        return {"node": committed}
    except Exception as e:
        raise _service_error_to_http(e)


@router.get("/nodes/{node_id}/audit")
async def list_node_audit(
    node_id: str,
    limit: int = Query(50, ge=1, le=500),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        events = await audit_service.list_events(
            db, user["user_id"], node_id, limit=limit
        )
        return {"events": events, "items": events, "count": len(events)}
    except Exception as e:
        raise _service_error_to_http(e)


@router.get("/nodes/{node_id}")
async def get_node(
    node_id: str,
    projection: str = Query("core"),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await node_service.get_node(db, user["user_id"], node_id, projection)
    except Exception as e:
        raise _service_error_to_http(e)


@router.delete("/nodes/{node_id}")
async def delete_node(
    request: Request,
    node_id: str,
    delete_mode: str = Query("cascade"),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        expected = await _current_revision(db, node_id)
        await node_service.delete_node(
            db, user["user_id"], node_id, delete_mode=delete_mode
        )
        await _log_cli_audit(
            db,
            user,
            request,
            node_id=node_id,
            operation="delete_node",
            expected_revision=expected,
            result_revision=0,
            payload={"delete_mode": delete_mode},
        )
        return {"deleted": True, "node_id": node_id}
    except Exception as e:
        raise _service_error_to_http(e)


@router.post("/nodes/{node_id}/commit")
async def commit_node(
    request: Request,
    node_id: str,
    body: dict[str, Any] | None = Body(None),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        payload = _body(body)
        params = (
            {"node_id": node_id, "payload_json": payload}
            if _looks_like_commit_envelope(payload)
            else {"node_id": node_id, **payload}
        )
        result = await _commit_existing_node(db, user, params)
        node = _node_from_result(result)
        if node and not result.get("error"):
            await _log_cli_audit(
                db,
                user,
                request,
                node_id=node_id,
                operation="commit_node",
                expected_revision=params.get("expected_revision"),
                result_revision=node.get("revision"),
                payload=payload,
            )
        return result
    except Exception as e:
        raise _service_error_to_http(e)


@router.post("/nodes/{node_id}/branch")
async def branch_node(
    request: Request,
    node_id: str,
    body: dict[str, Any] | None = Body(None),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        payload = _body(body)
        expected = payload.get("expected_revision")
        if expected is None:
            expected = await _current_revision(db, node_id)
        result = await node_service.branch_node(
            db,
            user["user_id"],
            BranchNodeRequest(
                node_id=node_id,
                expected_revision=expected,
                title=payload.get("title"),
                updated_by=payload.get("updated_by"),
            ),
        )
        await _log_cli_audit(
            db,
            user,
            request,
            node_id=node_id,
            operation="branch_node",
            expected_revision=expected,
            result_revision=result.get("parent_revision"),
            payload=payload,
        )
        child = _node_from_result(result)
        if child:
            await _log_cli_audit(
                db,
                user,
                request,
                node_id=child.get("node_id"),
                operation="branch_child_created",
                expected_revision=None,
                result_revision=child.get("revision"),
                payload=payload,
            )
        return result
    except Exception as e:
        raise _service_error_to_http(e)


@router.get("/nodes/{node_id}/children")
async def node_children(
    node_id: str,
    first: int = Query(100, ge=1, le=500),
    after: str | None = Query(None),
    projection: str = Query("topology"),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await node_service.list_node_relations(
            db,
            user["user_id"],
            node_id,
            direction="children",
            first=first,
            after=after,
            projection=projection,
        )
    except Exception as e:
        raise _service_error_to_http(e)


@router.get("/nodes/{node_id}/parents")
async def node_parents(
    node_id: str,
    first: int = Query(100, ge=1, le=500),
    after: str | None = Query(None),
    projection: str = Query("topology"),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await node_service.list_node_relations(
            db,
            user["user_id"],
            node_id,
            direction="parents",
            first=first,
            after=after,
            projection=projection,
        )
    except Exception as e:
        raise _service_error_to_http(e)


@router.post("/nodes/{node_id}/parents/add")
async def add_parent(
    request: Request,
    node_id: str,
    body: dict[str, Any] = Body(...),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        payload = _body(body)
        parent_id = payload.get("parent_id")
        if not parent_id:
            raise ValueError("parent_id is required")
        expected_parent = payload.get("expected_parent_revision")
        if expected_parent is None:
            expected_parent = await _current_revision(db, parent_id)
        node = await node_service.add_parent(
            db,
            user["user_id"],
            AddParentRequest(
                node_id=node_id,
                parent_id=parent_id,
                expected_revision=payload["expected_revision"],
                expected_parent_revision=expected_parent,
                updated_by=payload.get("updated_by"),
            ),
        )
        await _log_cli_audit(
            db,
            user,
            request,
            node_id=node_id,
            operation="add_parent",
            expected_revision=payload.get("expected_revision"),
            result_revision=node.get("revision"),
            payload=payload,
        )
        return {"node": node}
    except Exception as e:
        raise _service_error_to_http(e)


@router.post("/nodes/{node_id}/parents/remove")
async def remove_parent(
    request: Request,
    node_id: str,
    body: dict[str, Any] = Body(...),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        payload = _body(body)
        parent_id = payload.get("parent_id")
        if not parent_id:
            raise ValueError("parent_id is required")
        expected_parent = payload.get("expected_parent_revision")
        if expected_parent is None:
            expected_parent = await _current_revision(db, parent_id)
        node = await node_service.remove_parent(
            db,
            user["user_id"],
            RemoveParentRequest(
                node_id=node_id,
                parent_id=parent_id,
                expected_revision=payload["expected_revision"],
                expected_parent_revision=expected_parent,
                updated_by=payload.get("updated_by"),
            ),
        )
        await _log_cli_audit(
            db,
            user,
            request,
            node_id=node_id,
            operation="remove_parent",
            expected_revision=payload.get("expected_revision"),
            result_revision=node.get("revision"),
            payload=payload,
        )
        return {"node": node}
    except Exception as e:
        raise _service_error_to_http(e)


@router.get("/nodes/{node_id}/tree")
async def render_tree(
    node_id: str,
    projection: str = Query("core"),
    max_nodes: int = Query(5000, ge=1, le=10000),
    max_depth: int | None = Query(None, ge=0, le=1000),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await node_service.get_node_tree(
            db,
            user["user_id"],
            node_id,
            projection=projection,
            max_nodes=max_nodes,
            max_depth=max_depth,
        )
    except Exception as e:
        raise _service_error_to_http(e)


@router.get("/nodes/{node_id}/ancestry")
async def render_ancestry(
    node_id: str,
    projection: str = Query("core"),
    max_depth: int = Query(256, ge=1, le=1000),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await node_service.get_node_ancestry(
            db, user["user_id"], node_id, projection=projection, max_depth=max_depth
        )
    except Exception as e:
        raise _service_error_to_http(e)


@router.get("/nodes/{node_id}/summary")
async def render_summary(
    node_id: str,
    max_nodes: int = Query(200, ge=1, le=10000),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await node_service.summarize_node_tree(
            db, user["user_id"], node_id, max_nodes=max_nodes
        )
    except Exception as e:
        raise _service_error_to_http(e)


@router.get("/nodes/{node_id}/files")
async def node_files(
    node_id: str,
    include_descendants: bool = Query(False),
    max_nodes: int = Query(200, ge=1, le=10000),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await artifact_service.list_files(
            db,
            user["user_id"],
            node_id,
            include_descendants=include_descendants,
            max_nodes=max_nodes,
        )
    except Exception as e:
        raise _service_error_to_http(e)


@router.get("/nodes/{node_id}/access-policy")
async def get_sharing(
    node_id: str,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await sharing_service.get_sharing(db, user["user_id"], node_id)
    except Exception as e:
        raise _service_error_to_http(e)


@router.put("/nodes/{node_id}/access-policy")
async def set_sharing(
    node_id: str,
    body: dict[str, Any] = Body(...),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        payload = _body(body)
        req = SetSharingRequest(
            node_id=node_id,
            sharing_mode=_coerce_sharing_mode(payload.get("sharing_mode")),
            collaborators=payload.get("collaborators"),
        )
        return await sharing_service.set_sharing(db, user["user_id"], node_id, req)
    except Exception as e:
        raise _service_error_to_http(e)


@router.post("/nodes/{node_id}/stage/lease/acquire")
async def acquire_stage_lease(
    node_id: str,
    body: dict[str, Any] | None = Body(None),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        payload = _body(body)
        expected = payload.get("expected_revision")
        if expected is None:
            expected = payload.get("base_committed_revision")
        lease = await stage_lease_service.acquire_stage_lease(
            db,
            user["user_id"],
            node_id=node_id,
            expected_revision=expected,
            stage_session_id=payload.get("stage_session_id"),
            ttl_seconds=payload.get("ttl_seconds", 1800),
            purpose=payload.get("purpose"),
        )
        return {
            "stage_lease": lease,
            "lease": {
                "stage_session_id": lease["stage_session_id"],
                "node_id": lease.get("node_id"),
                "base_committed_revision": lease.get("expected_revision"),
                "expires_at": lease.get("expires_at"),
                "heartbeat_interval_seconds": 15,
            },
            "stage_session_id": lease["stage_session_id"],
        }
    except Exception as e:
        raise _service_error_to_http(e)


async def _require_staged_backfill_target(
    db: aiosqlite.Connection,
    user: dict,
    node_id: str,
    expected_revision: int | None,
) -> dict[str, Any]:
    from atlas_graph.db.repos import node_repo

    if expected_revision is None:
        raise ValueError("expected_revision is required")
    await require_node_access(db, user["user_id"], node_id, "write")
    row = await node_repo.get_node(db, node_id)
    if row is None:
        raise ValueError(f"Node {node_id} not found")
    if row.get("lifecycle") != "staged":
        raise ValueError("backfill helpers require a staged node")
    if int(row["revision"]) != int(expected_revision):
        raise ValueError(
            f"409 conflict: expected revision {expected_revision}, current is {row['revision']}"
        )
    return row


@router.post("/nodes/{node_id}/stage/backfill/hypothesis")
async def backfill_stage_hypothesis(
    request: Request,
    node_id: str,
    body: dict[str, Any] | None = Body(None),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        payload = _body(body)
        expected_revision = payload.get("expected_revision")
        row = await _require_staged_backfill_target(
            db, user, node_id, expected_revision
        )
        generated = _derive_hypothesis(row)
        if row.get("hypothesis") and not payload.get("force"):
            node = await node_service.get_node(
                db, user["user_id"], node_id, projection="full"
            )
            return {"node": node, "generated": row.get("hypothesis"), "updated": False}
        node = await node_service.stage_update(
            db,
            user["user_id"],
            StageNodeUpdateRequest(
                node_id=node_id,
                expected_revision=int(expected_revision),
                hypothesis=generated,
            ),
        )
        await _log_cli_audit(
            db,
            user,
            request,
            node_id=node_id,
            operation="stage_backfill_hypothesis",
            expected_revision=expected_revision,
            result_revision=node.get("revision"),
            payload=payload,
        )
        return {"node": node, "generated": generated, "updated": True}
    except Exception as e:
        raise _service_error_to_http(e)


@router.post("/nodes/{node_id}/stage/backfill/insights")
async def backfill_stage_insights(
    request: Request,
    node_id: str,
    body: dict[str, Any] | None = Body(None),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        payload = _body(body)
        expected_revision = payload.get("expected_revision")
        row = await _require_staged_backfill_target(
            db, user, node_id, expected_revision
        )
        if row.get("node_type") == "empirical":
            raise ValueError(
                "insights backfill is only valid for insight or untyped staged nodes"
            )
        existing_raw = row.get("insights") or "[]"
        try:
            existing = (
                json.loads(existing_raw)
                if isinstance(existing_raw, str)
                else existing_raw
            )
        except (json.JSONDecodeError, TypeError):
            existing = []
        if existing and not payload.get("force"):
            node = await node_service.get_node(
                db, user["user_id"], node_id, projection="full"
            )
            return {"node": node, "generated": existing, "updated": False}
        generated = _derive_insights(row)
        node = await node_service.stage_update(
            db,
            user["user_id"],
            StageNodeUpdateRequest(
                node_id=node_id,
                expected_revision=int(expected_revision),
                insights=generated,
            ),
        )
        await _log_cli_audit(
            db,
            user,
            request,
            node_id=node_id,
            operation="stage_backfill_insights",
            expected_revision=expected_revision,
            result_revision=node.get("revision"),
            payload=payload,
        )
        return {"node": node, "generated": generated, "updated": True}
    except Exception as e:
        raise _service_error_to_http(e)


@router.post("/nodes/{node_id}/stage/lease/heartbeat")
async def heartbeat_stage_lease(
    node_id: str,
    body: dict[str, Any] = Body(...),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        payload = _body(body)
        lease = await stage_lease_service.heartbeat_stage_lease(
            db,
            user["user_id"],
            payload["stage_session_id"],
            ttl_seconds=payload.get("ttl_seconds", 1800),
        )
        return {
            "stage_lease": lease,
            "lease": {
                "stage_session_id": lease["stage_session_id"],
                "node_id": lease.get("node_id"),
                "base_committed_revision": lease.get("expected_revision"),
                "expires_at": lease.get("expires_at"),
                "heartbeat_interval_seconds": 15,
            },
        }
    except Exception as e:
        raise _service_error_to_http(e)


@router.post("/nodes/{node_id}/stage/lease/release")
async def release_stage_lease(
    node_id: str,
    body: dict[str, Any] = Body(...),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        payload = _body(body)
        lease = await stage_lease_service.release_stage_lease(
            db,
            user["user_id"],
            payload["stage_session_id"],
            reason=payload.get("reason", "released"),
        )
        return {"stage_lease": lease, "released": True}
    except Exception as e:
        raise _service_error_to_http(e)


@router.post("/nodes/{node_id}/remote-artifacts/resolve")
async def resolve_remote_artifact(
    node_id: str,
    body: dict[str, Any] = Body(...),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        payload = _body(body)
        return await node_service.resolve_remote_artifact(
            db, user["user_id"], node_id, **payload
        )
    except Exception as e:
        raise _service_error_to_http(e)


@router.post("/nodes/{node_id}/remote-artifacts/refresh")
async def refresh_remote_artifact(
    node_id: str,
    body: dict[str, Any] = Body(...),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        payload = _body(body)
        payload["force_refresh"] = True
        return await node_service.resolve_remote_artifact(
            db, user["user_id"], node_id, **payload
        )
    except Exception as e:
        raise _service_error_to_http(e)


@router.put("/nodes/{node_id}/tags")
async def assign_tags(
    node_id: str,
    body: dict[str, Any] = Body(...),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        payload = _body(body)
        return await tag_service.set_tag_assignments(
            db,
            user["user_id"],
            TagAssignment(
                node_id=node_id,
                expected_revision=payload["expected_revision"],
                tag_ids=_split_ids(payload.get("tag_ids")),
            ),
        )
    except Exception as e:
        raise _service_error_to_http(e)


@router.post("/nodes/{root_node_id}/tags")
async def create_tag(
    root_node_id: str,
    body: dict[str, Any] = Body(...),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await tag_service.create_tag(
            db, user["user_id"], TagCreate(root_node_id=root_node_id, **_body(body))
        )
    except Exception as e:
        raise _service_error_to_http(e)


@router.patch("/nodes/{root_node_id}/tags/{tag_id}")
async def update_tag(
    root_node_id: str,
    tag_id: str,
    body: dict[str, Any] = Body(...),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await tag_service.update_tag(
            db,
            user["user_id"],
            TagUpdate(root_node_id=root_node_id, tag_id=tag_id, **_body(body)),
        )
    except Exception as e:
        raise _service_error_to_http(e)


@router.delete("/nodes/{root_node_id}/tags/{tag_id}")
async def delete_tag(
    root_node_id: str,
    tag_id: str,
    body: dict[str, Any] | None = Body(None),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        await tag_service.delete_tag(
            db,
            user["user_id"],
            TagDelete(root_node_id=root_node_id, tag_id=tag_id, **_body(body)),
        )
        return {"deleted": True, "tag_id": tag_id}
    except Exception as e:
        raise _service_error_to_http(e)


@router.get("/nodes/{node_id}/artifacts")
async def list_artifacts(
    node_id: str,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await artifact_service.list_artifacts(db, user["user_id"], node_id)
    except Exception as e:
        raise _service_error_to_http(e)


@router.get("/nodes/{node_id}/artifacts/{artifact_id}")
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
    except Exception as e:
        raise _service_error_to_http(e)


@router.delete("/nodes/{node_id}/artifacts/{artifact_id}")
async def delete_artifact(
    node_id: str,
    artifact_id: str,
    body: dict[str, Any] | None = Body(None),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        result = await artifact_service.delete_artifact(
            db,
            user["user_id"],
            DeleteArtifactRequest(
                node_id=node_id,
                artifact_id=artifact_id,
                expected_revision=_body(body).get("expected_revision"),
            ),
        )
        return result
    except Exception as e:
        raise _service_error_to_http(e)


@router.post("/nodes/{node_id}/artifacts/bulk-delete")
async def delete_artifacts_bulk(
    node_id: str,
    body: dict[str, Any] = Body(...),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        payload = _body(body)
        req = SimpleNamespace(
            node_id=node_id,
            artifact_ids=_split_ids(payload.get("artifact_ids")),
            expected_revision=payload.get("expected_revision"),
            yes=True,
        )
        return await artifact_service.delete_artifacts_bulk(db, user["user_id"], req)
    except Exception as e:
        raise _service_error_to_http(e)


@router.patch("/nodes/{node_id}/artifacts/{artifact_id}/note")
async def set_artifact_note(
    node_id: str,
    artifact_id: str,
    body: dict[str, Any] | None = Body(None),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        payload = _body(body)
        return await artifact_service.set_artifact_note(
            db,
            user["user_id"],
            SetArtifactNoteRequest(
                node_id=node_id,
                artifact_id=artifact_id,
                expected_revision=payload.get("expected_revision"),
                note=payload.get("note"),
            ),
        )
    except Exception as e:
        raise _service_error_to_http(e)


@router.post(
    "/nodes/{node_id}/artifacts/uploads/prepare", status_code=status.HTTP_201_CREATED
)
async def prepare_uploads(
    node_id: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        payload = _body(body)
        result = await artifact_service.prepare_uploads(
            db,
            user["user_id"],
            PrepareUploadRequest(
                node_id=node_id,
                expected_revision=payload["expected_revision"],
                items=payload.get("items") or [],
            ),
        )
        return _rewrite_upload_urls(result, request)
    except Exception as e:
        raise _service_error_to_http(e)


@router.post("/nodes/{node_id}/artifacts/uploads/finalize")
async def finalize_uploads(
    node_id: str,
    body: dict[str, Any] = Body(...),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        payload = _body(body)
        return await artifact_service.finalize_uploads(
            db,
            user["user_id"],
            FinalizeUploadRequest(node_id=node_id, batch_token=payload["batch_token"]),
        )
    except Exception as e:
        raise _service_error_to_http(e)


@router.put("/artifacts/uploads/{upload_id}")
async def handle_ticket_upload(
    upload_id: str,
    request: Request,
    ticket: str = Query(...),
    db: aiosqlite.Connection = Depends(get_db),
):
    try:
        if not ticket.startswith("v1:"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Invalid ticket format"
            )
        payload = verify_signed_token(ticket[3:])
        if payload is None or payload.get("upload_id") != upload_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid or expired upload ticket",
            )
        node_id = payload.get("node_id")
        batch_token = payload.get("batch_token")
        if not node_id or not batch_token:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Upload ticket missing required claims",
            )
        data = await request.body()
        if len(data) > config.MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Upload exceeds maximum size of {config.MAX_UPLOAD_BYTES} bytes",
            )
        if not data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Empty request body"
            )
        content_type = request.headers.get(
            "Content-Type", payload.get("content_type") or "application/octet-stream"
        )
        filename = (
            request.headers.get("X-Atlas-Artifact-Filename")
            or request.headers.get("X-Thesis-Artifact-Filename")
            or "upload"
        )
        result = await artifact_service.handle_upload(
            db, upload_id, content_type, filename, data
        )
        return {
            "upload": {
                "upload_id": upload_id,
                "batch_token": batch_token,
                "staged": True,
            },
            **result,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise _service_error_to_http(e)


@router.get("/users/me/files")
async def list_files(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        public_node_access = (
            "OR n.sharing_mode IN ('public', 'unlisted') "
            if config.PUBLIC_GRAPHS_ENABLED
            else ""
        )
        public_root_access = (
            "OR r.sharing_mode IN ('public', 'unlisted') "
            if config.PUBLIC_GRAPHS_ENABLED
            else ""
        )
        access_sql = (
            "(n.owner_user_id = ? "
            + public_node_access
            + "OR EXISTS (SELECT 1 FROM node_access_rules ar WHERE ar.node_id = n.node_id AND ar.user_id = ?) "
            "OR EXISTS ("
            "  WITH RECURSIVE ancestors(current_id) AS ("
            "    SELECT n.node_id"
            "    UNION"
            "    SELECT e.parent_id FROM node_edges e JOIN ancestors a ON e.child_id = a.current_id"
            "  )"
            "  SELECT 1 FROM nodes r"
            "  WHERE r.node_id IN ("
            "    SELECT current_id FROM ancestors"
            "    WHERE current_id NOT IN (SELECT child_id FROM node_edges)"
            "  )"
            "  AND (r.owner_user_id = ? "
            + public_root_access
            + "       OR EXISTS (SELECT 1 FROM node_access_rules ar2 WHERE ar2.node_id = r.node_id AND ar2.user_id = ?))"
            "  LIMIT 1"
            "))"
        )
        storage_sql = "a.storage_path IS NOT NULL AND a.storage_path != ''"
        count_cursor = await db.execute(
            f"""
            SELECT COUNT(*)
            FROM artifacts a
            JOIN nodes n ON n.node_id = a.node_id
            WHERE {access_sql} AND {storage_sql}
            """,
            (user["user_id"], user["user_id"], user["user_id"], user["user_id"]),
        )
        total_count = (await count_cursor.fetchone())[0]
        offset = (page - 1) * page_size
        cursor = await db.execute(
            f"""
            SELECT
                a.artifact_id,
                a.node_id,
                a.artifact_type,
                a.title,
                a.metadata,
                a.execution_id,
                a.storage_path,
                a.created_at
            FROM artifacts a
            JOIN nodes n ON n.node_id = a.node_id
            WHERE {access_sql} AND {storage_sql}
            ORDER BY a.created_at DESC
            LIMIT ? OFFSET ?
            """,
            (
                user["user_id"],
                user["user_id"],
                user["user_id"],
                user["user_id"],
                page_size,
                offset,
            ),
        )
        columns = [desc[0] for desc in cursor.description]
        rows = [dict(zip(columns, row)) for row in await cursor.fetchall()]

        files: list[dict[str, Any]] = []
        for row in rows:
            metadata = row.get("metadata") or {}
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except (json.JSONDecodeError, TypeError):
                    metadata = {}
            storage_path = row["storage_path"]
            files.append(
                {
                    "file_id": row["artifact_id"],
                    "artifact_id": row["artifact_id"],
                    "node_id": row["node_id"],
                    "filename": row.get("title") or storage_path.rsplit("/", 1)[-1],
                    "artifact_type": row.get("artifact_type"),
                    "media_type": metadata.get("media_type"),
                    "storage_path": storage_path,
                    "storage_url": storage.get_signed_url(storage_path),
                    "metadata": metadata,
                    "execution_id": row.get("execution_id"),
                    "created_at": row.get("created_at", ""),
                }
            )
        return {
            "files": files,
            "count": len(files),
            "total_count": total_count,
            "page": page,
            "page_size": page_size,
        }
    except Exception as e:
        raise _service_error_to_http(e)














@router.get("/blobs")
async def get_blob(
    storage_path: str = Query(...),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        path = storage_path.lstrip("/")
        if not path:
            raise ValueError("storage_path is required")
        cursor = await db.execute(
            "SELECT node_id, title, metadata FROM artifacts WHERE storage_path = ?",
            (path,),
        )
        row = await cursor.fetchone()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="artifact not found"
            )
        node_id = row["node_id"]
        await require_node_access(db, user["user_id"], node_id, "view")
        try:
            data = await storage.download(path)
        except FileNotFoundError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="blob not found"
            )
        metadata = row["metadata"] or {}
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except (json.JSONDecodeError, TypeError):
                metadata = {}
        media_type = (
            metadata.get("media_type")
            or mimetypes.guess_type(path)[0]
            or "application/octet-stream"
        )
        filename = row["title"] or path.rsplit("/", 1)[-1]
        from atlas_graph.services.blob_serve import safe_blob_response

        # Inline preview for safe types; executable docs neutralized + forced
        # to download. XSS hardening.
        return safe_blob_response(
            content=data, media_type=media_type, filename=filename, inline=True
        )
    except HTTPException:
        raise
    except Exception as e:
        raise _service_error_to_http(e)


@router.get("/legacy/history/export.jsonl")
async def export_history_jsonl(
    node_ids: str | None = Query(None),
    include_descendants: bool = Query(False),
    max_nodes: int | None = Query(200),
    limit_per_node: int = Query(50, ge=1, le=500),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        ids = _split_ids(node_ids)
        if ids:
            payload = await export_import_service.export_history(
                db,
                user["user_id"],
                ids,
                include_descendants=include_descendants,
                max_nodes=max_nodes,
                limit_per_node=limit_per_node,
            )
            return _jsonl_response(payload.get("nodes") or [])
        cursor = await db.execute(
            """SELECT event_id, actor_user_id, oauth_client_id, node_id, operation,
                      idempotency_key, expected_revision, result_revision,
                      request_hash, timestamp
               FROM audit_events
               WHERE actor_user_id = ?
               ORDER BY timestamp DESC
               LIMIT ?""",
            (user["user_id"], limit_per_node),
        )
        columns = [desc[0] for desc in cursor.description]
        return _jsonl_response(
            [dict(zip(columns, row)) for row in await cursor.fetchall()]
        )
    except Exception as e:
        raise _service_error_to_http(e)


@router.post("/export")
async def export_subgraph(
    body: dict[str, Any] = Body(...),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        payload = _body(body)
        return await export_import_service.export_subgraph(
            db,
            user["user_id"],
            _split_ids(payload.get("node_ids")),
            include_descendants=payload.get("include_descendants", True),
            max_nodes=payload.get("max_nodes"),
        )
    except Exception as e:
        raise _service_error_to_http(e)


@router.post("/export-summary")
async def export_summary(
    body: dict[str, Any] = Body(...),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        node_ids = _split_ids(_body(body).get("node_ids"))
        markdown = await _summary_markdown(db, user["user_id"], node_ids)
        return {
            "title": "Research Summary",
            "markdown": markdown,
            "content": markdown,
            "node_count": len(node_ids),
        }
    except Exception as e:
        raise _service_error_to_http(e)


@router.post("/export-summary-stream")
async def export_summary_stream(
    body: dict[str, Any] = Body(...),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        markdown = await _summary_markdown(
            db, user["user_id"], _split_ids(_body(body).get("node_ids"))
        )
        return StreamingResponse(
            iter([markdown.encode("utf-8")]), media_type="text/markdown"
        )
    except Exception as e:
        raise _service_error_to_http(e)


@router.post("/export-summary-pdf")
async def export_summary_pdf(
    body: dict[str, Any] = Body(...),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        markdown = await _summary_markdown(
            db, user["user_id"], _split_ids(_body(body).get("node_ids"))
        )
        return _pdf_response(
            await run_in_threadpool(_markdown_to_pdf, markdown, title="Atlas Summary")
        )
    except Exception as e:
        raise _service_error_to_http(e)


@router.post("/export-summary-render-pdf")
async def export_summary_render_pdf(
    body: dict[str, Any] = Body(...),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        payload = _body(body)
        markdown = payload.get("markdown")
        if not markdown:
            markdown = await _summary_markdown(
                db, user["user_id"], _split_ids(payload.get("node_ids"))
            )
        return _pdf_response(
            await run_in_threadpool(
                _markdown_to_pdf,
                str(markdown),
                title=str(payload.get("title") or "Atlas Summary"),
            )
        )
    except Exception as e:
        raise _service_error_to_http(e)


@router.post("/import", status_code=status.HTTP_201_CREATED)
async def import_subgraph(
    body: dict[str, Any] = Body(...),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await export_import_service.import_subgraph(
            db, user["user_id"], _body(body)
        )
    except Exception as e:
        raise _service_error_to_http(e)


@router.post("/research/log", status_code=status.HTTP_201_CREATED)
async def research_log_append(
    body: dict[str, Any] = Body(...),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    payload = _body(body)
    project_id = str(payload.get("project_id") or "").strip()
    title = str(payload.get("title") or "").strip()
    if not project_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="project_id is required"
        )
    if not title:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="title is required"
        )
    try:
        await require_node_access(db, user["user_id"], project_id, "write")
        refs = payload.get("refs")
        if refs is None:
            refs = []
        if not isinstance(refs, list):
            raise ValueError("refs must be a list")
        entry = await research_log_service.append(
            db,
            project_id=project_id,
            entry_type=str(payload.get("entry_type") or "note").strip() or "note",
            title=title[:300],
            body=payload.get("body"),
            refs=refs,
            created_by=user["user_id"],
        )
        return {"ok": True, "entry": entry}
    except HTTPException:
        raise
    except Exception as e:
        raise _service_error_to_http(e)


@router.get("/research/log")
async def research_log_list(
    project_id: str = Query(...),
    entry_types: str | None = Query(None),
    since: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        await require_node_access(db, user["user_id"], project_id, "view")
        entries = await research_log_service.list_entries(
            db,
            project_id=project_id,
            entry_types=_split_strings(entry_types) or None,
            since=since,
            limit=limit,
        )
        return {"project_id": project_id, "count": len(entries), "entries": entries}
    except Exception as e:
        raise _service_error_to_http(e)


@router.post("/research/log/search")
async def research_log_search(
    body: dict[str, Any] = Body(...),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    payload = _body(body)
    project_id = str(payload.get("project_id") or "").strip()
    query = str(payload.get("query") or "").strip()
    if not project_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="project_id is required"
        )
    if not query:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="query is required"
        )
    try:
        await require_node_access(db, user["user_id"], project_id, "view")
        entries = await research_log_service.search(
            db,
            project_id=project_id,
            query=query,
            limit=int(payload.get("limit") or 20),
        )
        return {
            "project_id": project_id,
            "query": query,
            "count": len(entries),
            "entries": entries,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise _service_error_to_http(e)
