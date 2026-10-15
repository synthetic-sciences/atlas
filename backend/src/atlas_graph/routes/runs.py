"""Flight Recorder routes.

The recorder is agent-driven: a coding agent (Claude Code / Codex /
Cursor / a bare ``atlas`` shell call) sends a structured run summary
here after a training script exits, a notebook cell finishes, or an
eval prints. The route scrubs secrets, optionally folds repeats into a
cluster, and stores the result as an ``empirical`` node under the
project.

Thin first pass: ingest + scrub + node create. ``distill`` and
``runs:compare`` land in follow-up commits. ``run_cluster_key`` is
accepted and persisted but cluster merging is not yet performed -
callers may rely on it being unique-or-null today.

Public surface:
- ``POST /api/v1/runs:record`` body / response shapes below.
"""

from __future__ import annotations

import json
import re
from typing import Any

import aiosqlite
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status

from atlas_graph.auth.access_check import require_node_access
from atlas_graph.db.repos import node_repo
from atlas_graph.dependencies import get_current_user, get_db
from atlas_graph.models.common import NodeOutcome
from atlas_graph.models.node import (
    CommitNodeRequest,
    StageNodeCreateRequest,
    StageNodeUpdateRequest,
)
from atlas_graph.services import node_service
from atlas_graph.services.node_service import apply_semantics, parse_node_semantics
from atlas_graph.services.scrub import scrub_payload

router = APIRouter(prefix="/api/v1", tags=["flight-recorder"])


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

# User-facing outcome → stored ``NodeOutcome``. The CLI body uses
# success/failure/inconclusive because that's what an agent writing
# capture code would reach for; the DB has historically tracked
# completed/failed/canceled so the names diverge intentionally.
_OUTCOME_MAP: dict[str, NodeOutcome] = {
    "success": NodeOutcome.completed,
    "failure": NodeOutcome.failed,
    "inconclusive": NodeOutcome.inconclusive,
    # Accept the stored names too so callers that already speak the DB
    # vocabulary aren't forced to translate.
    "completed": NodeOutcome.completed,
    "failed": NodeOutcome.failed,
    "canceled": NodeOutcome.canceled,
}

_VALID_FAILURE_MODES = {
    "diverged",
    "oom",
    "data_bug",
    "code_bug",
    "underperformed",
    "other",
}


_SCORECARD_MAX_ITEMS = 200


def _validate_scorecard(raw: Any) -> dict[str, Any] | None:
    """Normalize an ``evaluation_v1`` scorecard, or 422 on malformed input.

    The scorecard is the per-example verdict vector behind the graph's
    pass/fail rings. Caps keep it a summary, not a blob: 200 items max,
    each item reduced to ``ref`` / ``score`` / ``pass`` (+ short feedback).
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise HTTPException(status_code=422, detail="scorecard must be an object")
    items_raw = raw.get("items")
    if not isinstance(items_raw, list) or not items_raw:
        raise HTTPException(
            status_code=422, detail="scorecard.items must be a non-empty list"
        )
    if len(items_raw) > _SCORECARD_MAX_ITEMS:
        raise HTTPException(
            status_code=422,
            detail=f"scorecard.items exceeds {_SCORECARD_MAX_ITEMS} items",
        )
    items: list[dict[str, Any]] = []
    passed = 0
    for i, item in enumerate(items_raw):
        if not isinstance(item, dict):
            raise HTTPException(
                status_code=422, detail=f"scorecard.items[{i}] must be an object"
            )
        score = item.get("score")
        if score is not None:
            try:
                score = float(score)
            except (TypeError, ValueError):
                raise HTTPException(
                    status_code=422,
                    detail=f"scorecard.items[{i}].score must be numeric",
                )
        ok = bool(item.get("pass", (score or 0) > 0))
        if ok:
            passed += 1
        cleaned: dict[str, Any] = {"ref": str(item.get("ref", f"ex_{i}"))[:120], "pass": ok}
        if score is not None:
            cleaned["score"] = score
        feedback = item.get("feedback")
        if isinstance(feedback, str) and feedback.strip():
            cleaned["feedback"] = feedback.strip()[:500]
        items.append(cleaned)
    aggregate_raw = raw.get("aggregate") if isinstance(raw.get("aggregate"), dict) else {}
    agg_score = aggregate_raw.get("score")
    if agg_score is not None:
        try:
            agg_score = float(agg_score)
        except (TypeError, ValueError):
            agg_score = None
    return {
        "spec": "evaluation_v1",
        "metric": str(raw.get("metric", ""))[:120] or None,
        "items": items,
        "aggregate": {"score": agg_score, "n": len(items), "passed": passed},
    }


def _infer_outcome(exit_code: Any) -> NodeOutcome:
    """Default outcome when the caller didn't supply one.

    ``exit_code == 0`` → success. Any non-zero → failure. Missing exit
    code (the agent didn't capture one) → inconclusive, on purpose, so
    the matrix render can flag "this run is unclassified" instead of
    silently labelling it a success.
    """
    if exit_code is None:
        return NodeOutcome.inconclusive
    try:
        return NodeOutcome.completed if int(exit_code) == 0 else NodeOutcome.failed
    except (TypeError, ValueError):
        return NodeOutcome.inconclusive


def _format_content(payload: dict[str, Any]) -> str:
    """Render the run payload as a readable markdown body for the node.

    The node's ``content`` is the main human-facing surface in the
    dashboard, so we lay the run out in sections rather than dumping the
    raw JSON. ``distill`` will rewrite this in a later commit; today we
    just want it legible.
    """
    parts: list[str] = []
    title = payload.get("title")
    if title:
        parts.append(f"# {title}")
    # An EVAL.md-style results doc leads the body so a run reads results-first.
    # This is the "results contract": one obvious, human-readable results
    # surface per node, the same role EVAL.md plays for an experiment.
    eval_md = payload.get("eval_markdown")
    if isinstance(eval_md, str) and eval_md.strip():
        parts.append(eval_md.strip())
    config = payload.get("config")
    if config:
        parts.append("## config")
        for k, v in sorted((config or {}).items()):
            parts.append(f"- `{k}` = `{v}`")
    metrics = payload.get("metrics")
    if metrics:
        parts.append("## metrics")
        for k, v in sorted((metrics or {}).items()):
            parts.append(f"- `{k}` = `{v}`")
    stdout_tail = payload.get("stdout_tail")
    if stdout_tail:
        parts.append("## stdout (tail)")
        parts.append("```")
        parts.append(str(stdout_tail).rstrip())
        parts.append("```")
    return "\n".join(parts) if parts else (title or "run")


# Success criteria are caller-supplied strings evaluated against run
# data, so they're parsed with a strict regex - one dot-path, one
# comparator, one numeric literal. Anything else → criterion_met=None.
# Never eval().
_CRITERION_RE = re.compile(
    r"^\s*([a-zA-Z0-9_./]+)\s*(<=|>=|<|>|==|!=)\s*(-?\d+(?:\.\d+)?)\s*$"
)

_CRITERION_OPS = {
    "<=": lambda a, b: a <= b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    ">": lambda a, b: a > b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}


def _evaluate_criterion(criterion: Any, run_payload: dict[str, Any]) -> bool | None:
    """Evaluate a plan's success criterion against {config, metrics}.

    Returns True/False on a clean comparison, None when the criterion is
    unparseable or the referenced value is missing / non-numeric - the
    matrix shows "unknown" rather than guessing.
    """
    if not criterion or not isinstance(criterion, str):
        return None
    match = _CRITERION_RE.match(criterion)
    if not match:
        return None
    path, op, target_raw = match.groups()
    value = _lookup_dot_path(run_payload, path)
    try:
        return _CRITERION_OPS[op](float(value), float(target_raw))
    except (TypeError, ValueError):
        return None


def _build_title(payload: dict[str, Any], outcome: NodeOutcome) -> str:
    """Best-effort title when the caller didn't provide one.

    Prefers ``model`` / ``task`` / ``experiment`` keys from config so the
    title means something in the dashboard list view.
    """
    if payload.get("title"):
        return str(payload["title"])
    config = payload.get("config") or {}
    for key in ("experiment", "task", "model", "name"):
        v = config.get(key)
        if v:
            return f"{v} ({outcome.value})"
    return f"run ({outcome.value})"


# ---------------------------------------------------------------------------
# POST /runs:record
# ---------------------------------------------------------------------------

@router.post("/runs:record", status_code=status.HTTP_201_CREATED)
async def runs_record(
    request: Request,
    body: dict[str, Any] = Body(...),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Record a single experiment run as an ``empirical`` node.

    Body fields (all optional unless marked required):

    - ``project_id`` (**required**) - parent project node. Must be owned
      by the caller.
    - ``title`` - human title for the node. Derived from
      ``config.experiment`` / ``config.task`` / ``config.model`` /
      ``config.name`` if omitted.
    - ``config`` - dict of hyperparameters / model / dataset.
    - ``metrics`` - dict of numeric results.
    - ``eval_markdown`` - an EVAL.md-style results doc (markdown). Rendered
      at the top of the node body so the run reads results-first; scrubbed
      before storage. The CLI auto-attaches a repo's ``EVAL.md`` here.
    - ``stdout_tail`` - last N lines of stdout for the run; scrubbed
      before storage.
    - ``exit_code`` - process exit code; used to infer ``outcome`` when
      the caller didn't supply one.
    - ``outcome`` - ``success`` | ``failure`` | ``inconclusive``.
      Defaults to inferred from ``exit_code``; missing exit_code stays
      inconclusive on purpose.
    - ``failure_mode`` - ``diverged`` | ``oom`` | ``data_bug`` |
      ``code_bug`` | ``underperformed`` | ``other``. Only meaningful
      when outcome=failure. Unknown values are coerced to ``other``.
    - ``run_cluster_key`` - stable string that groups repeats of the
      same experiment. Persisted today; cluster-merge semantics land
      next.
    - ``repo_url`` / ``branch_name`` / ``head_commit_sha`` - code state
      behind the run (the CLI auto-detects these from the working tree).
      Stored on the same node columns ``repo:capture`` writes.
    - ``git_dirty`` - true when the working tree had uncommitted changes
      at record time; kept in ``run_data`` so reproducibility checks can
      flag it.
    - ``plan_id`` - an owned experiment-plan node (semantic_data.type =
      ``experiment_plan``); the run is parented to it, inherits its
      ``run_cluster_key`` when the run has none, and its
      ``success_criterion`` is evaluated into ``criterion_met``.
    - ``hypothesis_id`` - an owned ``hypothesis`` node; used as an
      additional parent when no ``plan_id`` is given.
    - ``parent_run_id`` - an owned node this run descends from. Used by
      iterative optimizers (e.g. GEPA) to carry candidate lineage:
      candidate N parents to the candidate it mutated, so the graph
      renders a real search tree instead of a flat star.
    - ``candidate_idx`` - optimizer-assigned candidate index (int).
    - ``scorecard`` - per-example evaluation results
      (``evaluation_v1``: ``{"spec", "metric", "items": [{"ref",
      "score", "pass"}], "aggregate"}``). Capped at 200 items; stored
      in ``semantic_data`` so the graph can render pass/fail rings.

    Returns ``{"node": {…}, "redactions": int, "outcome": str,
    "criterion_met": bool | None}``.
    """
    payload = dict(body or {})
    project_id = payload.get("project_id")
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

    # Scrub strings first so nothing secret is observable downstream
    # (logs, audit, distill prompts, content).
    scrubbed, redactions = scrub_payload(payload)
    scrubbed_dict: dict[str, Any] = scrubbed if isinstance(scrubbed, dict) else {}

    raw_outcome = scrubbed_dict.get("outcome")
    if raw_outcome is None:
        outcome = _infer_outcome(scrubbed_dict.get("exit_code"))
    else:
        outcome = _OUTCOME_MAP.get(str(raw_outcome).lower())
        if outcome is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    "outcome must be one of: success, failure, inconclusive "
                    "(or the stored synonyms completed/failed/canceled)"
                ),
            )

    failure_mode_raw = scrubbed_dict.get("failure_mode")
    failure_mode: str | None = None
    if failure_mode_raw is not None:
        candidate = str(failure_mode_raw).lower().strip()
        failure_mode = candidate if candidate in _VALID_FAILURE_MODES else "other"

    cluster_key = scrubbed_dict.get("run_cluster_key")
    if cluster_key is not None and not isinstance(cluster_key, str):
        cluster_key = str(cluster_key)

    # Semantic-layer binding: a run can attach to the experiment plan it
    # executes (preferred) or directly to a hypothesis. Both become
    # additional parents so the DAG carries provenance.
    plan_id = scrubbed_dict.get("plan_id")
    hypothesis_id = scrubbed_dict.get("hypothesis_id")
    plan_semantics: dict[str, Any] | None = None
    parent_ids = [project_id]
    if plan_id is not None:
        if not isinstance(plan_id, str):
            plan_id = str(plan_id)
        plan = await node_repo.get_node(db, plan_id)
        if not plan:
            raise HTTPException(status_code=422, detail="plan_id not found")
        try:
            await require_node_access(db, user["user_id"], plan_id, "view")
        except Exception:
            raise HTTPException(status_code=422, detail="plan_id not found")
        plan_semantics = parse_node_semantics(plan)
        if plan_semantics.get("type") != "experiment_plan":
            raise HTTPException(
                status_code=422, detail="plan_id is not an experiment plan node"
            )
        parent_ids.append(plan_id)
        if cluster_key is None and plan_semantics.get("run_cluster_key"):
            cluster_key = plan_semantics["run_cluster_key"]
    if hypothesis_id is not None:
        if not isinstance(hypothesis_id, str):
            hypothesis_id = str(hypothesis_id)
        hyp = await node_repo.get_node(db, hypothesis_id)
        if (
            not hyp
            or hyp.get("node_type") != "hypothesis"
        ):
            raise HTTPException(
                status_code=422, detail="hypothesis_id is not an accessible hypothesis node"
            )
        try:
            await require_node_access(db, user["user_id"], hypothesis_id, "view")
        except Exception:
            raise HTTPException(
                status_code=422, detail="hypothesis_id is not an accessible hypothesis node"
            )
        if plan_id is None:
            parent_ids.append(hypothesis_id)

    # Candidate lineage: iterative optimizers parent each run to the run
    # it mutated. Any owned node qualifies (the parent is usually another
    # run, but a seed/baseline insight node is fine too).
    parent_run_id = scrubbed_dict.get("parent_run_id")
    if parent_run_id is not None:
        if not isinstance(parent_run_id, str):
            parent_run_id = str(parent_run_id)
        parent_run = await node_repo.get_node(db, parent_run_id)
        if not parent_run:
            raise HTTPException(
                status_code=422, detail="parent_run_id is not an accessible node"
            )
        try:
            await require_node_access(db, user["user_id"], parent_run_id, "view")
        except Exception:
            raise HTTPException(
                status_code=422, detail="parent_run_id is not an accessible node"
            )
        if parent_run_id not in parent_ids:
            parent_ids.append(parent_run_id)

    candidate_idx = scrubbed_dict.get("candidate_idx")
    if candidate_idx is not None:
        try:
            candidate_idx = int(candidate_idx)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="candidate_idx must be an int")

    scorecard = _validate_scorecard(scrubbed_dict.get("scorecard"))

    title = _build_title(scrubbed_dict, outcome)
    content = _format_content(scrubbed_dict)
    summary = scrubbed_dict.get("summary") or title

    # Stage → update → commit, mirroring how /nodes creates an insight
    # node. ``kind="empirical"`` is the canonical type for a run.
    #
    # The commit-time validator on empirical nodes requires a non-empty
    # ``hypothesis``; for a run this is "what was the agent trying to
    # do" — fall back to the title when the caller didn't say. Likewise
    # an empirical node with outcome="completed" needs either attached
    # artifacts or ``no_artifacts_reason`` — runs typically don't ship
    # artifact files through this route (yet), so we set a default
    # reason that the dashboard can render.
    hypothesis = (
        scrubbed_dict.get("hypothesis")
        or scrubbed_dict.get("title")
        or summary
        or title
    )
    staged = await node_service.stage_create(
        db,
        user["user_id"],
        StageNodeCreateRequest(
            title=title,
            summary=summary,
            content=content,
            kind="empirical",
            hypothesis=hypothesis,
            parent_ids=parent_ids,
        ),
    )
    staged = await node_service.stage_update(
        db,
        user["user_id"],
        StageNodeUpdateRequest(
            node_id=staged["node_id"],
            expected_revision=staged["revision"],
            outcome=outcome,
            no_artifacts_reason=(
                "captured via runs:record (metrics/stdout inline; "
                "no external artifact uploaded)"
            ),
        ),
    )
    committed = await node_service.commit_node(
        db,
        user["user_id"],
        CommitNodeRequest(
            node_id=staged["node_id"],
            expected_revision=staged["revision"],
            summary=summary,
        ),
    )
    if committed is None:
        raise HTTPException(status_code=500, detail="failed to commit run node")

    # Direct column writes for the Flight Recorder attributes -
    # they're not in StageNodeUpdateRequest (and don't need to be;
    # callers should always reach them through this route). ``run_data``
    # is the structured form of the captured run: config, metrics,
    # exit_code. Stored as a JSON string alongside the markdown
    # ``content`` so ``runs:compare`` can pivot across runs without
    # re-parsing markdown.
    extras: dict[str, Any] = {}
    if failure_mode is not None:
        extras["failure_mode"] = failure_mode
    if cluster_key is not None:
        extras["run_cluster_key"] = cluster_key

    # Code-state capture ("GitHub for science"): the CLI auto-detects the
    # caller's git state and sends it along, so every run is linked to the
    # exact code that produced it without the agent having to remember a
    # separate repo:capture call. Stored on the same node columns
    # repo:capture writes, so reproduce / public code viewing read one place.
    for column in ("repo_url", "branch_name", "head_commit_sha"):
        value = scrubbed_dict.get(column)
        if value is not None and str(value).strip():
            extras[column] = str(value).strip()[:500]

    run_data = {
        "config": scrubbed_dict.get("config"),
        "metrics": scrubbed_dict.get("metrics"),
        "exit_code": scrubbed_dict.get("exit_code"),
        # True when the working tree had uncommitted changes at record time -
        # the sha alone would overstate reproducibility in that case.
        "git_dirty": scrubbed_dict.get("git_dirty"),
    }
    # Drop None entries so the matrix doesn't show ghost columns.
    run_data = {k: v for k, v in run_data.items() if v is not None}
    if run_data:
        extras["run_data"] = json.dumps(run_data)

    # Criterion evaluation: when the bound plan declares a
    # success_criterion, score this run against it. Unparseable
    # criterion or missing metric → None (unknown), never a guess.
    criterion_met: bool | None = None
    if plan_semantics is not None and plan_semantics.get("success_criterion"):
        criterion_met = _evaluate_criterion(
            plan_semantics["success_criterion"],
            {
                "config": scrubbed_dict.get("config") or {},
                "metrics": scrubbed_dict.get("metrics") or {},
            },
        )

    # Every recorded run carries type="run" + its metrics in semantic_data so
    # the graph renderer can read the score directly (the progression layout
    # positions runs by it, the node run-header shows it) instead of only
    # finding it in the title or the result body.
    metrics = scrubbed_dict.get("metrics") or None
    run_semantics: dict[str, Any] | None = None
    if (
        metrics
        or plan_id is not None
        or hypothesis_id is not None
        or parent_run_id is not None
        or candidate_idx is not None
        or scorecard is not None
    ):
        run_semantics = {
            "type": "run",
            "plan_id": plan_id,
            "hypothesis_id": hypothesis_id
            or (plan_semantics or {}).get("hypothesis_id"),
            "criterion_met": criterion_met,
        }
        if metrics:
            run_semantics["metrics"] = metrics
        if parent_run_id is not None:
            run_semantics["parent_run_id"] = parent_run_id
        if candidate_idx is not None:
            run_semantics["candidate_idx"] = candidate_idx
        if scorecard is not None:
            run_semantics["scorecard"] = scorecard

    if run_semantics is not None or extras:
        committed = (
            await apply_semantics(db, committed["node_id"], run_semantics, extras)
            or committed
        )

    return {
        "node": committed,
        "redactions": redactions,
        "outcome": outcome.value,
        "criterion_met": criterion_met,
    }


# ---------------------------------------------------------------------------
# GET /runs:compare
# ---------------------------------------------------------------------------

# Default columns when the caller doesn't specify any. Picked to be
# legible without needing to know which config/metric fields exist:
# "what was the run, did it work, and how was it grouped".
_DEFAULT_COMPARE_COLUMNS = (
    "title",
    "outcome",
    "failure_mode",
    "run_cluster_key",
    "created_at",
)

# Columns that live directly on the node row (no dot-path lookup).
_NODE_COLUMN_KEYS = {
    "node_id",
    "title",
    "summary",
    "outcome",
    "failure_mode",
    "run_cluster_key",
    "seeded",
    "created_at",
    "updated_at",
}


def _lookup_dot_path(payload: Any, path: str) -> Any:
    """Resolve ``a.b.c`` against a nested dict, returning ``None`` if
    any segment is missing. Lists are not indexed (callers shouldn't
    need it for matrix rows); falsy-but-present values are returned
    as-is so the table render can show 0 / False / "" honestly."""
    if not path:
        return None
    cur: Any = payload
    for segment in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(segment)
        if cur is None:
            return None
    return cur


def _sort_key(value: Any) -> tuple[int, float, str]:
    """Numeric-aware sort key: numbers (and numeric strings) sort
    together, other values sort as strings after them. ``None`` is
    handled by the caller (always last, regardless of direction)."""
    if isinstance(value, bool):
        value = int(value)
    if isinstance(value, (int, float)):
        return (0, float(value), "")
    try:
        return (0, float(value), "")
    except (TypeError, ValueError):
        return (1, 0.0, str(value))


@router.get("/runs:compare")
async def runs_compare(
    request: Request,
    root: str = Query(..., description="Project node id (parent of the runs)."),
    cluster: str | None = Query(None, description="Filter to a single run_cluster_key."),
    columns: str | None = Query(
        None,
        description=(
            "Comma-separated columns. Node columns are read directly "
            "(``title``, ``outcome``, ``failure_mode``, ``run_cluster_key``, "
            "``created_at``…); dot-paths into the captured run data are "
            "supported as ``config.<k>`` / ``metrics.<k>``. Defaults to "
            "title/outcome/failure_mode/run_cluster_key/created_at."
        ),
    ),
    outcome: str | None = Query(None, description="Filter rows by outcome (e.g. failed)."),
    sort: str | None = Query(
        None,
        description=(
            "Sort rows by a node column or a ``config.<k>`` / "
            "``metrics.<k>`` dot-path. Numeric-aware; None values last."
        ),
    ),
    direction: str = Query("asc", description="Sort direction: asc or desc."),
    best: bool = Query(
        False, description="Include the top row (after sorting) as ``best``."
    ),
    fmt: str = Query("json", alias="format", description="json or table."),
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Render the comparison matrix across runs under one project.

    The data already lives on the run nodes (``run_data`` JSON +
    ``outcome`` / ``failure_mode`` / ``run_cluster_key`` columns); this
    route just pivots them into a table. No LLM, no chart engine - just
    SQL + dot-path lookups - so it can be called freely from the CLI
    after every run without cost concerns.

    Returns ``{root_node_id, cluster, columns, rows, count}``. When
    ``format=table`` is requested an additional ``table`` field carries a
    markdown rendering so terminal callers can ``echo`` it directly.
    """
    if direction not in ("asc", "desc"):
        raise HTTPException(status_code=422, detail="direction must be asc or desc")

    project = await node_repo.get_node(db, root)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    try:
        await require_node_access(db, user["user_id"], root, "view")
    except Exception:
        raise HTTPException(status_code=404, detail="project not found")

    # Bounded descendant walk: runs bound to an experiment plan are
    # parented under the plan node, not directly under the project, so a
    # direct-children query would miss them. Depth ≤ 3, ≤ 500 rows.
    node_rows = await node_repo.get_descendants(
        db, root, user["user_id"], max_depth=3, limit=500, node_type="empirical"
    )

    if cluster is not None:
        node_rows = [n for n in node_rows if n.get("run_cluster_key") == cluster]
    if outcome is not None:
        node_rows = [n for n in node_rows if n.get("outcome") == outcome]

    requested_columns = (
        [c.strip() for c in columns.split(",") if c.strip()]
        if columns
        else list(_DEFAULT_COMPARE_COLUMNS)
    )

    rows: list[dict[str, Any]] = []
    sort_values: list[Any] = []
    for node in node_rows:
        # Parse run_data once per node so multiple config.* / metrics.*
        # columns share the deserialised dict.
        raw = node.get("run_data")
        try:
            run_payload = json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            run_payload = {}
        semantics = parse_node_semantics(node)

        def _column_value(col: str) -> Any:
            if col == "criterion_met":
                # Semantic-layer column: lives in semantic_data, written
                # when the run was bound to a plan with a criterion.
                return semantics.get("criterion_met")
            if col in _NODE_COLUMN_KEYS:
                return node.get(col)
            if col.startswith("config.") or col.startswith("metrics."):
                return _lookup_dot_path(run_payload, col)
            # Unknown columns return None rather than 422 - lets
            # callers be sloppy about which fields exist on which
            # runs without exploding the query.
            return None

        row: dict[str, Any] = {"node_id": node["node_id"]}
        for col in requested_columns:
            row[col] = _column_value(col)
        rows.append(row)
        if sort is not None:
            sort_values.append(_column_value(sort))

    if sort is not None:
        # None values always sort last, regardless of direction, so the
        # "best" row never ends up being a run that didn't report the
        # metric at all.
        paired = list(zip(rows, sort_values))
        present = [p for p in paired if p[1] is not None]
        missing = [p for p in paired if p[1] is None]
        present.sort(key=lambda p: _sort_key(p[1]), reverse=(direction == "desc"))
        rows = [p[0] for p in present + missing]

    result: dict[str, Any] = {
        "root_node_id": root,
        "cluster": cluster,
        "outcome_filter": outcome,
        "columns": requested_columns,
        "rows": rows,
        "count": len(rows),
    }
    if sort is not None:
        result["sort"] = sort
        result["direction"] = direction
    if best:
        result["best"] = rows[0] if rows else None
    if fmt == "table":
        result["table"] = _render_markdown_table(requested_columns, rows)
    return result


def _render_markdown_table(columns: list[str], rows: list[dict[str, Any]]) -> str:
    """Tiny markdown table renderer.

    Keeps the table render in-process so terminals can pipe the matrix
    straight into a shell pager. Big charts and rich rendering belong in
    a follow-up (this is why ``formalize/`` wasn't ported wholesale)."""
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body_lines = []
    for row in rows:
        cells = []
        for col in columns:
            v = row.get(col)
            if v is None:
                cells.append("")
            elif isinstance(v, bool):
                cells.append("true" if v else "false")
            else:
                cells.append(str(v))
        body_lines.append("| " + " | ".join(cells) + " |")
    return "\n".join([header, sep, *body_lines])
