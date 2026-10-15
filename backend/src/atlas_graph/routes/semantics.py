"""Research semantic layer routes ("research verbs").

The Flight Recorder (routes/runs.py) captures what *happened*; these
routes capture what the researcher *means*: hypotheses under test,
planned experiments, recorded decisions, and eval definitions. Each verb
stores its structured payload in the node's ``semantic_data`` JSON
column beside the human-readable markdown ``content``, so the agent
context packet (``/projects/{id}/brief``) and ``runs:compare`` can read
structure without re-parsing prose.

All verbs mirror runs:record exactly: ownership check → scrub → caps →
stage_create → (stage_update → commit_node) → semantic column write via
``node_service.apply_semantics``.

Public surface:
- ``POST /api/v1/hypotheses:add``
- ``POST /api/v1/hypotheses:update``
- ``POST /api/v1/experiments:plan``
- ``POST /api/v1/decisions:add``
- ``POST /api/v1/evals:define``
- ``POST /api/v1/optimize:progress``
- ``GET  /api/v1/projects/{project_id}/brief``
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import aiosqlite
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status

from atlas_graph.auth.access_check import require_node_access
from atlas_graph.db.repos import node_repo
from atlas_graph.dependencies import get_current_user, get_db
from atlas_graph.models.common import NodeKind, NodeOutcome
from atlas_graph.models.node import (
    CommitNodeRequest,
    StageNodeCreateRequest,
    StageNodeUpdateRequest,
)
from atlas_graph.services import node_service, research_log_service
from atlas_graph.services.node_service import apply_semantics, parse_node_semantics
from atlas_graph.services.scrub import scrub_payload

router = APIRouter(prefix="/api/v1", tags=["research-verbs"])


# ---------------------------------------------------------------------------
# Vocabulary + caps
# ---------------------------------------------------------------------------

_HYPOTHESIS_STATUSES = ("proposed", "testing", "supported", "weakened", "rejected")
_CONFIDENCE_LEVELS = ("low", "medium", "high")
_EVAL_DIRECTIONS = ("min", "max")

_MAX_LIST_ITEMS = 20
_MAX_STRING_LEN = 10_000
_MAX_BASIS_IDS = 8
_TITLE_LEN = 120

# Brief section caps. ``?full=true`` triples everything.
_BRIEF_CAPS = {
    "nodes": 800,
    "hypotheses": 12,
    "recent_runs": 10,
    "decisions": 8,
    "open_branches": 8,
    "suggested_next": 5,
    "recent_activity": 12,
}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _enforce_caps(value: Any, path: str = "body") -> None:
    """Reject oversized payloads before they reach storage.

    Lists are capped at 20 items and strings at 10k chars anywhere in the
    body - these verbs store prose + small structured lists, not blobs.
    """
    if isinstance(value, str):
        if len(value) > _MAX_STRING_LEN:
            raise HTTPException(
                status_code=422,
                detail=f"{path} exceeds {_MAX_STRING_LEN} characters",
            )
    elif isinstance(value, list):
        if len(value) > _MAX_LIST_ITEMS:
            raise HTTPException(
                status_code=422,
                detail=f"{path} exceeds {_MAX_LIST_ITEMS} items",
            )
        for i, item in enumerate(value):
            _enforce_caps(item, f"{path}[{i}]")
    elif isinstance(value, dict):
        for k, v in value.items():
            _enforce_caps(v, f"{path}.{k}")


async def _require_owned_project(
    db: aiosqlite.Connection, user: dict, project_id: Any
) -> dict[str, Any]:
    """project_id required + graph-write accessible, with the runs:record 404 shape."""
    if not project_id or not isinstance(project_id, str):
        raise HTTPException(status_code=422, detail="project_id is required")
    project = await node_repo.get_node(db, project_id)
    if not project:
        # Same shape as get_node's 404 — don't leak ownership-vs-existence.
        raise HTTPException(status_code=404, detail="project not found")
    try:
        await require_node_access(db, user["user_id"], project_id, "write")
    except Exception:
        raise HTTPException(status_code=404, detail="project not found")
    return project


def _required_str(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not value or not isinstance(value, str) or not value.strip():
        raise HTTPException(status_code=422, detail=f"{field} is required")
    return value.strip()


def _optional_str(payload: dict[str, Any], field: str) -> str | None:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail=f"{field} must be a string")
    return value


def _string_list(payload: dict[str, Any], field: str) -> list[str]:
    value = payload.get(field)
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise HTTPException(
            status_code=422, detail=f"{field} must be a list of strings"
        )
    return value


def _enum_value(
    payload: dict[str, Any], field: str, allowed: tuple[str, ...], default: str | None
) -> str:
    raw = payload.get(field)
    if raw is None:
        if default is None:
            raise HTTPException(status_code=422, detail=f"{field} is required")
        return default
    candidate = str(raw).lower().strip()
    if candidate not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"{field} must be one of: {', '.join(allowed)}",
        )
    return candidate


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "experiment"


def _truncate(text: str, limit: int = _TITLE_LEN) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _markdown_sections(title: str, sections: list[tuple[str, Any]]) -> str:
    """Render labelled sections the same way runs.py lays out a run -
    legible markdown, never raw JSON."""
    parts: list[str] = [f"# {title}"]
    for heading, value in sections:
        if value is None or value == [] or value == {}:
            continue
        parts.append(f"## {heading}")
        if isinstance(value, dict):
            for k, v in sorted(value.items()):
                parts.append(f"- `{k}` = `{v}`")
        elif isinstance(value, list):
            for item in value:
                parts.append(f"- {item}")
        else:
            parts.append(str(value))
    return "\n".join(parts)


async def _create_semantic_node(
    db: aiosqlite.Connection,
    user: dict,
    *,
    title: str,
    summary: str,
    content: str,
    kind: NodeKind,
    parent_ids: list[str],
    semantic_data: dict[str, Any],
    commit: bool = True,
) -> dict[str, Any]:
    """stage → (update → commit) → semantic write, mirroring runs:record.

    Plan / eval nodes stay ``kind=untyped`` and therefore *staged*:
    commit_node hard-rejects untyped nodes by design, and these are
    scaffolding rather than results.
    """
    staged = await node_service.stage_create(
        db,
        user["user_id"],
        StageNodeCreateRequest(
            title=title,
            summary=summary,
            content=content,
            kind=kind,
            parent_ids=parent_ids,
        ),
    )
    node_id = staged["node_id"]
    if commit:
        staged = await node_service.stage_update(
            db,
            user["user_id"],
            StageNodeUpdateRequest(
                node_id=node_id,
                expected_revision=staged["revision"],
                # commit_node requires an outcome; semantic nodes record a
                # statement that simply exists, so "completed" it is.
                outcome=NodeOutcome.completed,
            ),
        )
        committed = await node_service.commit_node(
            db,
            user["user_id"],
            CommitNodeRequest(
                node_id=node_id,
                expected_revision=staged["revision"],
                summary=summary,
            ),
        )
        if committed is None:
            raise HTTPException(status_code=500, detail="failed to commit node")

    node = await apply_semantics(db, node_id, semantic_data)
    if node is None:
        raise HTTPException(status_code=500, detail="failed to persist semantics")
    return node


# ---------------------------------------------------------------------------
# POST /hypotheses:add
# ---------------------------------------------------------------------------

@router.post("/hypotheses:add", status_code=status.HTTP_201_CREATED)
async def hypotheses_add(
    request: Request,
    body: dict[str, Any] = Body(...),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Record a falsifiable claim as a ``hypothesis`` node under the project.

    Body fields:

    - ``project_id`` (**required**) - parent project node, owned by caller.
    - ``claim`` (**required**) - the falsifiable statement.
    - ``rationale`` - why the claim is plausible.
    - ``assumptions`` / ``expected_observations`` / ``disconfirmers`` -
      lists of strings (≤ 20 each).
    - ``status`` - proposed | testing | supported | weakened | rejected
      (default ``proposed``).

    Returns ``{"node": {…}, "redactions": int}``.
    """
    payload = dict(body or {})
    await _require_owned_project(db, user, payload.get("project_id"))

    scrubbed, redactions = scrub_payload(payload)
    scrubbed_dict: dict[str, Any] = scrubbed if isinstance(scrubbed, dict) else {}
    _enforce_caps(scrubbed_dict)

    claim = _required_str(scrubbed_dict, "claim")
    rationale = _optional_str(scrubbed_dict, "rationale")
    assumptions = _string_list(scrubbed_dict, "assumptions")
    expected_observations = _string_list(scrubbed_dict, "expected_observations")
    disconfirmers = _string_list(scrubbed_dict, "disconfirmers")
    status_value = _enum_value(scrubbed_dict, "status", _HYPOTHESIS_STATUSES, "proposed")

    title = _truncate(claim)
    content = _markdown_sections(
        title,
        [
            ("claim", claim),
            ("rationale", rationale),
            ("assumptions", assumptions),
            ("expected observations", expected_observations),
            ("disconfirmers", disconfirmers),
            ("status", status_value),
        ],
    )
    semantic_data = {
        "type": "hypothesis",
        "status": status_value,
        "claim": claim,
        "rationale": rationale,
        "assumptions": assumptions,
        "expected_observations": expected_observations,
        "disconfirmers": disconfirmers,
        "basis_node_ids": [],
    }

    node = await _create_semantic_node(
        db,
        user,
        title=title,
        summary=claim,
        content=content,
        kind=NodeKind.hypothesis,
        parent_ids=[scrubbed_dict["project_id"]],
        semantic_data=semantic_data,
    )
    return {"node": node, "redactions": redactions}


# ---------------------------------------------------------------------------
# POST /hypotheses:update
# ---------------------------------------------------------------------------

@router.post("/hypotheses:update", status_code=status.HTTP_201_CREATED)
async def hypotheses_update(
    request: Request,
    body: dict[str, Any] = Body(...),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Move a hypothesis through its status lifecycle.

    Body fields:

    - ``node_id`` (**required**) - hypothesis node, owned by caller.
    - ``status`` (**required**) - proposed | testing | supported |
      weakened | rejected.
    - ``because`` - node ids that justify the transition; unioned into
      ``semantic_data.basis_node_ids`` (capped at 20).
    - ``note`` - free-text annotation appended to the status line.

    Appends "— status → <status> (<date>)" to the node's content so the
    history stays legible in the dashboard. Returns ``{"node": {…}}``.
    """
    payload = dict(body or {})
    node_id = payload.get("node_id")
    if not node_id or not isinstance(node_id, str):
        raise HTTPException(status_code=422, detail="node_id is required")

    node = await node_repo.get_node(db, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="node not found")
    try:
        await require_node_access(db, user["user_id"], node_id, "write")
    except Exception:
        raise HTTPException(status_code=404, detail="node not found")
    if node.get("node_type") != "hypothesis":
        raise HTTPException(status_code=422, detail="node is not a hypothesis")

    scrubbed, redactions = scrub_payload(payload)
    scrubbed_dict: dict[str, Any] = scrubbed if isinstance(scrubbed, dict) else {}
    _enforce_caps(scrubbed_dict)

    status_value = _enum_value(scrubbed_dict, "status", _HYPOTHESIS_STATUSES, None)
    because = _string_list(scrubbed_dict, "because")
    note = _optional_str(scrubbed_dict, "note")

    semantics = parse_node_semantics(node)
    semantics["status"] = status_value
    basis = [b for b in (semantics.get("basis_node_ids") or []) if isinstance(b, str)]
    for ref in because:
        if ref not in basis:
            basis.append(ref)
    semantics["basis_node_ids"] = basis[:_MAX_LIST_ITEMS]

    stamp = datetime.now(timezone.utc).date().isoformat()
    line = f"\n\n— status → {status_value} ({stamp})"
    if note:
        line += f": {note}"
    content = (node.get("content") or "") + line

    updated = await apply_semantics(db, node_id, semantics, {"content": content})
    return {"node": updated, "redactions": redactions}


# ---------------------------------------------------------------------------
# POST /experiments:plan
# ---------------------------------------------------------------------------

@router.post("/experiments:plan", status_code=status.HTTP_201_CREATED)
async def experiments_plan(
    request: Request,
    body: dict[str, Any] = Body(...),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Plan an experiment against a hypothesis, before any run exists.

    Body fields:

    - ``project_id`` (**required**) - parent project node.
    - ``hypothesis_id`` (**required**) - owned ``hypothesis`` node the
      plan tests (422 otherwise).
    - ``title`` / ``config`` / ``metric`` / ``success_criterion`` /
      ``expected_result`` / ``risks`` / ``run_cluster_key`` - optional
      plan detail. ``success_criterion`` is the machine-checkable form
      (e.g. ``metrics.val_loss <= 0.5``) that runs:record evaluates when
      a run binds to this plan via ``plan_id``.

    The plan node is parented to both the project and the hypothesis.
    Returns ``{"node": {…}, "redactions": int}``.
    """
    payload = dict(body or {})
    await _require_owned_project(db, user, payload.get("project_id"))

    hypothesis_id = payload.get("hypothesis_id")
    if not hypothesis_id or not isinstance(hypothesis_id, str):
        raise HTTPException(status_code=422, detail="hypothesis_id is required")
    hyp = await node_repo.get_node(db, hypothesis_id)
    if not hyp or hyp.get("node_type") != "hypothesis":
        raise HTTPException(
            status_code=422, detail="hypothesis_id must be an accessible hypothesis node"
        )
    try:
        await require_node_access(db, user["user_id"], hypothesis_id, "write")
    except Exception:
        raise HTTPException(
            status_code=422, detail="hypothesis_id must be an accessible hypothesis node"
        )

    scrubbed, redactions = scrub_payload(payload)
    scrubbed_dict: dict[str, Any] = scrubbed if isinstance(scrubbed, dict) else {}
    _enforce_caps(scrubbed_dict)

    config = scrubbed_dict.get("config")
    if config is not None and not isinstance(config, dict):
        raise HTTPException(status_code=422, detail="config must be an object")
    metric = _optional_str(scrubbed_dict, "metric")
    success_criterion = _optional_str(scrubbed_dict, "success_criterion")
    expected_result = _optional_str(scrubbed_dict, "expected_result")
    risks = _string_list(scrubbed_dict, "risks")
    cluster_key = _optional_str(scrubbed_dict, "run_cluster_key")

    title = _optional_str(scrubbed_dict, "title")
    if not title:
        if metric:
            title = f"plan: {metric}"
        elif expected_result:
            title = f"plan: {expected_result[:80]}"
        else:
            title = "plan: experiment"
    if not cluster_key:
        cluster_key = f"plan/{_slugify(title)}"

    content = _markdown_sections(
        title,
        [
            ("hypothesis", hyp.get("title")),
            ("config", config),
            ("metric", metric),
            ("success criterion", success_criterion),
            ("expected result", expected_result),
            ("risks", risks),
            ("run cluster key", cluster_key),
        ],
    )
    semantic_data = {
        "type": "experiment_plan",
        "hypothesis_id": hypothesis_id,
        "config": config,
        "metric": metric,
        "success_criterion": success_criterion,
        "expected_result": expected_result,
        "risks": risks,
        "run_cluster_key": cluster_key,
    }

    node = await _create_semantic_node(
        db,
        user,
        title=title,
        summary=expected_result or title,
        content=content,
        kind=NodeKind.untyped,
        parent_ids=[scrubbed_dict["project_id"], hypothesis_id],
        semantic_data=semantic_data,
        commit=False,
    )
    return {"node": node, "redactions": redactions}


# ---------------------------------------------------------------------------
# POST /decisions:add
# ---------------------------------------------------------------------------

@router.post("/decisions:add", status_code=status.HTTP_201_CREATED)
async def decisions_add(
    request: Request,
    body: dict[str, Any] = Body(...),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Record a decision (and what it was based on) as a ``decision`` node.

    Body fields:

    - ``project_id`` (**required**) - parent project node.
    - ``decision`` (**required**) - what was decided.
    - ``alternatives`` - options that were considered and not taken.
    - ``basis`` - up to 8 owned node ids the decision rests on; each
      becomes an additional parent edge so provenance is walkable.
    - ``confidence`` - low | medium | high (default ``medium``).
    - ``reversible`` - bool (default ``true``).

    Returns ``{"node": {…}, "redactions": int}``.
    """
    payload = dict(body or {})
    await _require_owned_project(db, user, payload.get("project_id"))

    scrubbed, redactions = scrub_payload(payload)
    scrubbed_dict: dict[str, Any] = scrubbed if isinstance(scrubbed, dict) else {}
    _enforce_caps(scrubbed_dict)

    decision = _required_str(scrubbed_dict, "decision")
    alternatives = _string_list(scrubbed_dict, "alternatives")
    basis = _string_list(scrubbed_dict, "basis")
    if len(basis) > _MAX_BASIS_IDS:
        raise HTTPException(
            status_code=422, detail=f"basis exceeds {_MAX_BASIS_IDS} node ids"
        )
    basis_rows = await node_repo.get_nodes_by_ids(db, basis)
    for ref in basis:
        row = basis_rows.get(ref)
        if not row:
            raise HTTPException(
                status_code=422, detail=f"basis node not found: {ref}"
            )
        try:
            await require_node_access(db, user["user_id"], ref, "view")
        except Exception:
            raise HTTPException(
                status_code=422, detail=f"basis node not found: {ref}"
            )
    confidence = _enum_value(scrubbed_dict, "confidence", _CONFIDENCE_LEVELS, "medium")
    reversible = scrubbed_dict.get("reversible", True)
    if not isinstance(reversible, bool):
        raise HTTPException(status_code=422, detail="reversible must be a boolean")

    title = _truncate(decision)
    content = _markdown_sections(
        title,
        [
            ("decision", decision),
            ("alternatives considered", alternatives),
            ("basis", basis),
            ("confidence", confidence),
            ("reversible", "yes" if reversible else "no"),
        ],
    )
    semantic_data = {
        "type": "decision",
        "alternatives": alternatives,
        "basis_node_ids": basis,
        "confidence": confidence,
        "reversible": reversible,
    }

    node = await _create_semantic_node(
        db,
        user,
        title=title,
        summary=decision,
        content=content,
        kind=NodeKind.decision,
        parent_ids=[scrubbed_dict["project_id"], *basis],
        semantic_data=semantic_data,
    )
    return {"node": node, "redactions": redactions}


# ---------------------------------------------------------------------------
# POST /evals:define
# ---------------------------------------------------------------------------

@router.post("/evals:define", status_code=status.HTTP_201_CREATED)
async def evals_define(
    request: Request,
    body: dict[str, Any] = Body(...),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Define a named evaluation metric for the project.

    Body fields:

    - ``project_id`` (**required**) - parent project node.
    - ``name`` (**required**) - eval display name.
    - ``metric`` (**required**) - dot-path into recorded run data,
      e.g. ``metrics.val_loss``.
    - ``direction`` (**required**) - ``min`` | ``max``.
    - ``threshold`` - numeric pass bar.
    - ``dataset_ref`` - which dataset the eval is defined over.

    Returns ``{"node": {…}, "redactions": int}``.
    """
    payload = dict(body or {})
    await _require_owned_project(db, user, payload.get("project_id"))

    scrubbed, redactions = scrub_payload(payload)
    scrubbed_dict: dict[str, Any] = scrubbed if isinstance(scrubbed, dict) else {}
    _enforce_caps(scrubbed_dict)

    name = _required_str(scrubbed_dict, "name")
    metric = _required_str(scrubbed_dict, "metric")
    direction = _enum_value(scrubbed_dict, "direction", _EVAL_DIRECTIONS, None)
    threshold = scrubbed_dict.get("threshold")
    if threshold is not None and (
        isinstance(threshold, bool) or not isinstance(threshold, (int, float))
    ):
        raise HTTPException(status_code=422, detail="threshold must be a number")
    dataset_ref = _optional_str(scrubbed_dict, "dataset_ref")

    title = f"eval: {name}"
    content = _markdown_sections(
        title,
        [
            ("metric", metric),
            ("direction", direction),
            ("threshold", threshold),
            ("dataset", dataset_ref),
        ],
    )
    semantic_data = {
        "type": "eval",
        "name": name,
        "metric": metric,
        "direction": direction,
        "threshold": threshold,
        "dataset_ref": dataset_ref,
    }

    node = await _create_semantic_node(
        db,
        user,
        title=title,
        summary=f"{name}: {direction}imise {metric}",
        content=content,
        kind=NodeKind.untyped,
        parent_ids=[scrubbed_dict["project_id"]],
        semantic_data=semantic_data,
        commit=False,
    )
    return {"node": node, "redactions": redactions}


# ---------------------------------------------------------------------------
# POST /optimize:progress
# ---------------------------------------------------------------------------

# Fields an optimizer may merge into its control node, with light type
# guards. Everything is optional per call - the first call usually sets
# the contract (objective/target/metric/budget_total), later calls tick
# budget_used/best_score, the final call sets status + stop_reason.
_OPTIMIZE_STR_FIELDS = ("objective", "target", "metric", "status", "stop_reason", "best_node_id", "run_dir")
_OPTIMIZE_NUM_FIELDS = ("budget_total", "budget_used", "stall_limit", "best_score", "pareto_size", "candidates_evaluated")
_OPTIMIZE_STATUSES = ("running", "done", "error", "stopped")
_OPTIMIZE_STOP_REASONS = (
    "budget_exhausted",
    "no_improvement",
    "objective_met",
    "user_cancelled",
    "runtime_error",
)


@router.post("/optimize:progress")
async def optimize_progress(
    body: dict[str, Any] = Body(...),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Merge optimizer run state into a control node's ``semantic_data``.

    The control node is an ordinary owned node (usually ``insight``) that
    heads an optimization run (e.g. GEPA). This route lets the optimizer
    stream live progress - budget used, best score, pareto size, final
    stop_reason - without round-tripping the node's content markdown.
    ``semantic_data.type`` is forced to ``optimize_run``.

    Body fields (all optional except ``node_id``):

    - ``node_id`` (**required**) - owned control node.
    - ``objective`` / ``target`` / ``metric`` / ``run_dir`` - run contract.
    - ``status`` - ``running`` | ``done`` | ``error`` | ``stopped``.
    - ``budget_total`` / ``budget_used`` / ``stall_limit`` - budget state.
    - ``best_score`` / ``best_node_id`` - current best candidate.
    - ``pareto_size`` / ``candidates_evaluated`` - search state.
    - ``stop_reason`` - one of ``budget_exhausted`` | ``no_improvement`` |
      ``objective_met`` | ``user_cancelled`` | ``runtime_error``.

    Returns ``{"node": {…}}`` with the refreshed node.
    """
    payload = dict(body or {})
    node_id = payload.get("node_id")
    if not node_id or not isinstance(node_id, str):
        raise HTTPException(status_code=422, detail="node_id is required")
    node = await node_repo.get_node(db, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="node not found")
    try:
        await require_node_access(db, user["user_id"], node_id, "write")
    except Exception:
        raise HTTPException(status_code=404, detail="node not found")

    scrubbed, _ = scrub_payload(payload)
    scrubbed_dict: dict[str, Any] = scrubbed if isinstance(scrubbed, dict) else {}
    # run_dir is a local filesystem path (".atlas-optimize/run-<ts>"), not a
    # secret; the entropy scrubber false-positives on it. Restore the raw
    # value — optimize:stop needs it byte-exact to find gepa.stop.
    if isinstance(payload.get("run_dir"), str):
        scrubbed_dict["run_dir"] = payload["run_dir"][:500]
    _enforce_caps(scrubbed_dict)

    semantics = parse_node_semantics(node)
    existing_type = semantics.get("type")
    if existing_type not in (None, "optimize_run"):
        raise HTTPException(
            status_code=422,
            detail=f"node already carries semantic type {existing_type!r}",
        )

    updates: dict[str, Any] = {}
    for field in _OPTIMIZE_STR_FIELDS:
        value = scrubbed_dict.get(field)
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            raise HTTPException(status_code=422, detail=f"{field} must be a string")
        updates[field] = value.strip()[:_MAX_STRING_LEN]
    if "status" in updates and updates["status"] not in _OPTIMIZE_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"status must be one of: {', '.join(_OPTIMIZE_STATUSES)}",
        )
    if "stop_reason" in updates and updates["stop_reason"] not in _OPTIMIZE_STOP_REASONS:
        raise HTTPException(
            status_code=422,
            detail=f"stop_reason must be one of: {', '.join(_OPTIMIZE_STOP_REASONS)}",
        )
    for field in _OPTIMIZE_NUM_FIELDS:
        value = scrubbed_dict.get(field)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise HTTPException(status_code=422, detail=f"{field} must be a number")
        updates[field] = value

    if not updates:
        raise HTTPException(status_code=422, detail="no recognized fields to update")

    semantics.update(updates)
    semantics["type"] = "optimize_run"
    semantics["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    refreshed = await apply_semantics(db, node_id, semantics)
    return {"node": refreshed}


# ---------------------------------------------------------------------------
# GET /projects/{project_id}/brief
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/brief")
async def project_brief(
    project_id: str,
    full: bool = Query(False, description="Triple all section caps."),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """The agent context packet: everything a coding agent needs to pick
    up a research project cold, in one bounded response.

    Pure SQL + Python over the descendant graph (depth ≤ 3) - no LLM, so
    it can be polled freely. Sections: project, hypotheses (with
    tested-by counts), recent runs, failure groups, decisions, open
    branches, and deterministic next-step suggestions with runnable
    ``atlas`` commands.
    """
    project = await node_repo.get_node(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    try:
        await require_node_access(db, user["user_id"], project_id, "view")
    except Exception:
        raise HTTPException(status_code=404, detail="project not found")

    mult = 3 if full else 1
    caps = {k: v * mult for k, v in _BRIEF_CAPS.items()}

    nodes = await node_repo.get_descendants(
        db, project_id, user["user_id"], max_depth=3, limit=caps["nodes"]
    )
    semantics = {n["node_id"]: parse_node_semantics(n) for n in nodes}

    def _created(n: dict[str, Any]) -> str:
        return str(n.get("created_at") or "")

    hypothesis_nodes = [n for n in nodes if n.get("node_type") == "hypothesis"]
    decision_nodes = [n for n in nodes if n.get("node_type") == "decision"]
    run_nodes = [n for n in nodes if n.get("node_type") == "empirical"]
    plan_nodes = [
        n for n in nodes if semantics[n["node_id"]].get("type") == "experiment_plan"
    ]

    # --- hypotheses -------------------------------------------------------
    # tested_by counts plan/run nodes whose semantics point back at the
    # hypothesis (runs may reference it transitively through their plan).
    plan_hypothesis: dict[str, str | None] = {
        p["node_id"]: semantics[p["node_id"]].get("hypothesis_id") for p in plan_nodes
    }

    def _run_hypothesis_id(run: dict[str, Any]) -> str | None:
        sem = semantics[run["node_id"]]
        if sem.get("hypothesis_id"):
            return sem["hypothesis_id"]
        return plan_hypothesis.get(sem.get("plan_id"))

    tested_by: dict[str, int] = {}
    last_activity: dict[str, str] = {}
    for h in hypothesis_nodes:
        last_activity[h["node_id"]] = str(h.get("updated_at") or _created(h))
    for n in plan_nodes + run_nodes:
        if n.get("node_type") == "empirical":
            hyp_id = _run_hypothesis_id(n)
        else:
            hyp_id = plan_hypothesis.get(n["node_id"])
        if hyp_id and hyp_id in last_activity:
            tested_by[hyp_id] = tested_by.get(hyp_id, 0) + 1
            last_activity[hyp_id] = max(last_activity[hyp_id], _created(n))

    hypotheses = []
    for h in hypothesis_nodes[: caps["hypotheses"]]:
        sem = semantics[h["node_id"]]
        hypotheses.append(
            {
                "node_id": h["node_id"],
                "title": h.get("title"),
                "claim": sem.get("claim") or h.get("title"),
                "status": sem.get("status") or "proposed",
                "tested_by": tested_by.get(h["node_id"], 0),
                "last_activity": last_activity.get(h["node_id"]),
            }
        )

    # --- recent runs ------------------------------------------------------
    runs_newest_first = sorted(run_nodes, key=_created, reverse=True)
    recent_runs = [
        {
            "node_id": n["node_id"],
            "title": n.get("title"),
            "outcome": n.get("outcome"),
            "failure_mode": n.get("failure_mode"),
            "run_cluster_key": n.get("run_cluster_key"),
            "criterion_met": semantics[n["node_id"]].get("criterion_met"),
            "created_at": n.get("created_at"),
        }
        for n in runs_newest_first[: caps["recent_runs"]]
    ]

    # --- failures grouped by mode ----------------------------------------
    failure_groups: dict[str, dict[str, Any]] = {}
    for n in run_nodes:
        if n.get("outcome") != "failed":
            continue
        mode = n.get("failure_mode") or "unspecified"
        group = failure_groups.setdefault(
            mode, {"mode": mode, "count": 0, "example_node_id": n["node_id"]}
        )
        group["count"] += 1
    failures = sorted(failure_groups.values(), key=lambda g: -g["count"])

    # --- decisions --------------------------------------------------------
    decisions = [
        {
            "node_id": n["node_id"],
            "title": n.get("title"),
            "confidence": semantics[n["node_id"]].get("confidence"),
            "created_at": n.get("created_at"),
        }
        for n in sorted(decision_nodes, key=_created, reverse=True)[: caps["decisions"]]
    ]

    # --- open branches: committed leaves that aren't decisions ------------
    node_ids = [n["node_id"] for n in nodes]
    child_counts: dict[str, int] = {}
    if node_ids:
        placeholders = ",".join("?" for _ in node_ids)
        cursor = await db.execute(
            f"SELECT parent_id, COUNT(*) AS c FROM node_edges "
            f"WHERE parent_id IN ({placeholders}) GROUP BY parent_id",
            node_ids,
        )
        try:
            for row in await cursor.fetchall():
                r = dict(row)
                child_counts[r["parent_id"]] = r["c"]
        finally:
            await cursor.close()

    open_branch_nodes = [
        n
        for n in sorted(nodes, key=_created)
        if n.get("lifecycle") == "committed"
        and n.get("node_type") != "decision"
        and child_counts.get(n["node_id"], 0) == 0
    ]
    open_branches = [
        {
            "node_id": n["node_id"],
            "title": n.get("title"),
            "kind": n.get("node_type"),
            "created_at": n.get("created_at"),
        }
        for n in open_branch_nodes[: caps["open_branches"]]
    ]

    # --- suggested next steps (deterministic, ordered a→d) ----------------
    suggested_next: list[dict[str, Any]] = []

    for h in hypotheses:
        if h["status"] == "proposed" and h["tested_by"] == 0:
            suggested_next.append(
                {
                    "reason": f"hypothesis has never been tested: {h['title']}",
                    "node_id": h["node_id"],
                    "command": (
                        f"atlas experiment:plan --project {project_id} "
                        f"--hypothesis {h['node_id']}"
                    ),
                }
            )

    for group in failures:
        if group["count"] >= 2:
            suggested_next.append(
                {
                    "reason": (
                        f"{group['count']} runs failed with "
                        f"failure_mode={group['mode']} — investigate the pattern"
                    ),
                    "node_id": group["example_node_id"],
                    "command": (
                        f"atlas run:compare --project {project_id} --outcome failure"
                    ),
                }
            )

    # Plans with at least one bound run but no decision citing the plan
    # or any of its runs: the experiment ran, nothing was concluded.
    decision_basis: set[str] = set()
    for d in decision_nodes:
        for ref in semantics[d["node_id"]].get("basis_node_ids") or []:
            if isinstance(ref, str):
                decision_basis.add(ref)
    for p in plan_nodes:
        plan_runs = [
            r for r in run_nodes if semantics[r["node_id"]].get("plan_id") == p["node_id"]
        ]
        if not plan_runs:
            continue
        cited = p["node_id"] in decision_basis or any(
            r["node_id"] in decision_basis for r in plan_runs
        )
        if not cited:
            suggested_next.append(
                {
                    "reason": (
                        f"plan has {len(plan_runs)} run(s) but no recorded "
                        f"decision: {p.get('title')}"
                    ),
                    "node_id": p["node_id"],
                    "command": (
                        f"atlas decision:add --project {project_id} "
                        f"--basis {p['node_id']}"
                    ),
                }
            )

    hyp_status = {h["node_id"]: h["status"] for h in hypotheses}
    weakened_suggested: set[str] = set()
    for n in run_nodes:
        if semantics[n["node_id"]].get("criterion_met") is not False:
            continue
        hyp_id = _run_hypothesis_id(n)
        if (
            hyp_id
            and hyp_id not in weakened_suggested
            and hyp_status.get(hyp_id) in ("proposed", "testing")
        ):
            weakened_suggested.add(hyp_id)
            suggested_next.append(
                {
                    "reason": (
                        "a run missed its success criterion but the hypothesis "
                        "is still marked " + hyp_status[hyp_id]
                    ),
                    "node_id": hyp_id,
                    "command": (
                        f"atlas hypothesis:update --node {hyp_id} --status weakened"
                    ),
                }
            )

    # --- recent ambient activity ------------------------------------------
    # The research log is where the ambient layer (web:search/web:fetch logging,
    # log:append breadcrumbs, the post-tool hook) records the research process.
    # Surfacing a compact slice here keeps that capture from being write-only:
    # the next agent/human picking up the project sees what was already tried.
    recent_activity: list[dict[str, Any]] = []
    try:
        entries = await research_log_service.list_entries(
            db, project_id=project_id, limit=caps["recent_activity"]
        )
        recent_activity = [
            {
                "entry_type": e.get("entry_type"),
                "title": e.get("title"),
                "created_at": e.get("created_at"),
                "refs": len(e.get("refs") or []),
            }
            for e in entries
        ]
    except Exception:
        recent_activity = []

    return {
        "project": {
            "node_id": project["node_id"],
            "title": project.get("title"),
            "summary": project.get("summary"),
            "created_at": project.get("created_at"),
        },
        "hypotheses": hypotheses,
        "recent_runs": recent_runs,
        "failures": failures,
        "decisions": decisions,
        "open_branches": open_branches,
        "recent_activity": recent_activity,
        "suggested_next": suggested_next[: caps["suggested_next"]],
        "caps": caps,
    }
