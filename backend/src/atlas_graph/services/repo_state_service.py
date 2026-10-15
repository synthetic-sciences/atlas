"""Capture and pin repository state for research-map nodes.

This is deterministic graph plumbing. It intentionally has no dependency on
the retired hosted Agent runtime: callers provide the repository, branch, and
commit observed in their own workspace, and Atlas records or pins that exact
state.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import aiosqlite
from fastapi import HTTPException

from atlas_graph.db.repos import node_repo
from atlas_graph.models.node import StageNodeUpdateRequest
from atlas_graph.services import node_service


def _parse_repo_url(repo_url: str) -> tuple[str, str] | None:
    value = (repo_url or "").strip().rstrip("/")
    if value.startswith("git@github.com:"):
        value = value[len("git@github.com:") :]
    for prefix in ("https://github.com/", "http://github.com/", "github.com/"):
        if value.startswith(prefix):
            value = value[len(prefix) :]
            break
    if value.endswith(".git"):
        value = value[:-4]
    parts = value.split("/")
    if len(parts) < 2 or not parts[0] or not parts[1]:
        return None
    return parts[0], parts[1]


async def _resolve_github_auth(
    db: aiosqlite.Connection,
    user_id: str,
    *,
    owner: str | None = None,
) -> str | None:
    try:
        from atlas_graph.services import github_auth_service

        return await github_auth_service.get_user_access_token(
            db,
            user_id=user_id,
            owner=owner,
        )
    except Exception:
        return None


async def _merge_code_state(
    db: aiosqlite.Connection,
    node_id: str,
    *,
    repo_url: str | None = None,
    branch_name: str | None = None,
    head_commit_sha: str | None = None,
    pinned_tag: str | None = None,
    pinned_ref: str | None = None,
    pinned_sha: str | None = None,
) -> None:
    from atlas_graph.services.node_service import parse_node_semantics

    row = await node_repo.get_node(db, node_id)
    if row is None:
        return
    semantics = parse_node_semantics(row)
    code_state = semantics.get("code_state")
    if not isinstance(code_state, dict):
        code_state = {}
    for key, value in {
        "repo_url": repo_url,
        "branch_name": branch_name,
        "head_commit_sha": head_commit_sha,
        "pinned_tag": pinned_tag,
        "pinned_ref": pinned_ref,
        "pinned_sha": pinned_sha,
    }.items():
        if value:
            code_state[key] = value
    if pinned_tag or pinned_ref or pinned_sha:
        code_state["pinned_at"] = datetime.now(timezone.utc).isoformat()
    semantics["code_state"] = code_state
    await node_repo.update_node(db, node_id, {"semantic_data": json.dumps(semantics)})


async def pin(
    db: aiosqlite.Connection,
    *,
    user_id: str,
    node_id: str,
    sha: str | None = None,
    tag: str | None = None,
) -> dict[str, Any]:
    """Pin a recorded commit under an immutable Atlas tag."""
    from atlas_graph.clients import github_client

    node = await node_service.get_node(db, user_id, node_id)
    repo_url = node.get("repo_url")
    if not repo_url:
        raise HTTPException(status_code=404, detail="node has no repository linked")
    parsed = _parse_repo_url(repo_url)
    if parsed is None:
        raise HTTPException(status_code=400, detail=f"unrecognized repo_url: {repo_url}")
    owner, repo = parsed

    target_sha = (sha or node.get("head_commit_sha") or "").strip()
    if not target_sha:
        raise HTTPException(
            status_code=400,
            detail="no commit to pin: record head_commit_sha or pass sha after pushing it",
        )

    token = await _resolve_github_auth(db, user_id, owner=owner)
    if not token:
        raise HTTPException(
            status_code=400,
            detail="connect GitHub with Contents write access before pinning code",
        )

    slug = node.get("slug_name") or node_id
    target_tag = (tag or f"atlas/{slug}-r{int(node.get('revision', 0) or 0)}").strip()
    ref = f"refs/tags/{target_tag}"
    already = False
    try:
        await github_client.create_ref(
            f"{owner}/{repo}",
            ref,
            target_sha,
            auth_token=token,
        )
    except github_client.GitHubError as exc:
        if exc.status == 422:
            message = (exc.message or "").lower()
            if "already exists" in message or "reference already exists" in message:
                already = True
            else:
                raise HTTPException(
                    status_code=400,
                    detail="commit not found on the remote; push it before pinning",
                ) from exc
        elif exc.status in (401, 403):
            raise HTTPException(
                status_code=403,
                detail="GitHub rejected the write; reconnect with Contents write access",
            ) from exc
        elif exc.status == 404:
            raise HTTPException(status_code=404, detail="repository not found or no access") from exc
        else:
            raise HTTPException(status_code=502, detail=f"github: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"github: {exc}") from exc

    await _merge_code_state(
        db,
        node_id,
        repo_url=repo_url,
        branch_name=node.get("branch_name"),
        head_commit_sha=target_sha,
        pinned_tag=target_tag,
        pinned_ref=ref,
        pinned_sha=target_sha,
    )
    return {
        "pinned": True,
        "already_pinned": already,
        "repo": f"{owner}/{repo}",
        "ref": ref,
        "tag": target_tag,
        "sha": target_sha,
    }


async def capture(
    db: aiosqlite.Connection,
    *,
    user_id: str,
    node_id: str,
    repo_url: str | None = None,
    branch_name: str | None = None,
    head_commit_sha: str | None = None,
    pin_commit: bool = False,
    tag: str | None = None,
) -> dict[str, Any]:
    """Record caller-observed code state and optionally pin its commit."""
    node = await node_service.get_node(db, user_id, node_id)
    updated = await node_service.stage_update(
        db,
        user_id,
        StageNodeUpdateRequest(
            node_id=node_id,
            expected_revision=int(node.get("revision", 0) or 0),
            repo_url=repo_url,
            branch_name=branch_name,
            head_commit_sha=head_commit_sha,
            updated_by=user_id,
        ),
    )
    await _merge_code_state(
        db,
        node_id,
        repo_url=updated.get("repo_url"),
        branch_name=updated.get("branch_name"),
        head_commit_sha=updated.get("head_commit_sha"),
    )
    result: dict[str, Any] = {
        "node_id": node_id,
        "repo_url": updated.get("repo_url"),
        "branch_name": updated.get("branch_name"),
        "head_commit_sha": updated.get("head_commit_sha"),
        "pinned": False,
    }
    if not pin_commit:
        return result
    try:
        pinned = await pin(
            db,
            user_id=user_id,
            node_id=node_id,
            sha=head_commit_sha,
            tag=tag,
        )
        result.update(pinned)
    except HTTPException as exc:
        result["pin_error"] = exc.detail
    return result


async def verify(
    db: aiosqlite.Connection,
    *,
    user_id: str,
    node_id: str,
    sha: str | None = None,
    tag: str | None = None,
) -> dict[str, Any]:
    """Verify that captured code state is reachable on the remote."""
    from atlas_graph.clients import github_client
    from atlas_graph.services.node_service import parse_node_semantics

    node = await node_service.get_node(db, user_id, node_id)
    repo_url = node.get("repo_url")
    if not repo_url:
        raise HTTPException(status_code=404, detail="node has no repository linked")
    parsed = _parse_repo_url(repo_url)
    if parsed is None:
        raise HTTPException(status_code=400, detail=f"unrecognized repo_url: {repo_url}")
    owner, repo = parsed
    semantics = parse_node_semantics(node)
    code_state = semantics.get("code_state")
    if not isinstance(code_state, dict):
        code_state = {}
    target_sha = str(
        sha
        or node.get("head_commit_sha")
        or code_state.get("head_commit_sha")
        or ""
    ).strip()
    target_tag = str(tag or code_state.get("pinned_tag") or "").strip()
    token = await _resolve_github_auth(db, user_id, owner=owner)

    result: dict[str, Any] = {
        "repo": f"{owner}/{repo}",
        "sha": target_sha or None,
        "tag": target_tag or None,
        "commit_reachable": False,
        "tag_reachable": False,
    }
    if target_tag:
        try:
            ref_data = await github_client.get_ref(
                f"{owner}/{repo}",
                target_tag,
                auth_token=token,
            )
            obj = ref_data.get("object") if isinstance(ref_data, dict) else {}
            ref_sha = obj.get("sha") if isinstance(obj, dict) else None
            result.update({"tag_reachable": True, "tag_sha": ref_sha})
            if target_sha and ref_sha == target_sha:
                result["commit_reachable"] = True
        except github_client.GitHubError as exc:
            if exc.status not in (401, 403, 404):
                raise HTTPException(status_code=502, detail=f"github: {exc}") from exc

    if target_sha and not result["commit_reachable"]:
        try:
            await github_client.get_commit(
                f"{owner}/{repo}",
                target_sha,
                auth_token=token,
            )
            result["commit_reachable"] = True
        except github_client.GitHubError as exc:
            if exc.status in (401, 403):
                raise HTTPException(status_code=403, detail="GitHub rejected the read") from exc
            if exc.status != 404:
                raise HTTPException(status_code=502, detail=f"github: {exc}") from exc
    result["reachable"] = bool(
        result["tag_reachable"] or result["commit_reachable"]
    )
    return result
