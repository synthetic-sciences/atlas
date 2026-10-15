"""
Campaign service -- builds a campaign snapshot from the node graph
and the campaign_budgets table.
"""

from __future__ import annotations

import json
from typing import Any

from atlas_graph.auth.access_check import require_node_access
from atlas_graph.db.repos import node_repo, campaign_repo


def _parse_json_field(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _is_campaign_config_artifact(row: dict[str, Any]) -> bool:
    metadata = _parse_json_field(row.get("metadata"))
    payload = _parse_json_field(row.get("payload"))
    if metadata.get("campaign_role") == "config":
        return True
    return (
        metadata.get("version") == "campaign_config_v1"
        or payload.get("version") == "campaign_config_v1"
    )


async def get_snapshot(db, user_id: str, node_id: str) -> dict[str, Any]:
    """
    Build a structured campaign snapshot for the tree rooted at *node_id*.

    Returns:
        dict with root_node_id, root_title, node_count, kind_counts,
        lifecycle_counts, outcome_counts, budgets, config_status,
        submissions, submission_count, has_leaderboard.
    """
    await require_node_access(db, user_id, node_id, "view")

    # 1. Resolve to the root node
    root_id = await node_repo.find_root_node_id(db, node_id)
    if root_id is None:
        root_id = node_id

    root_row = await node_repo.get_node(db, root_id)
    if root_row is None:
        raise ValueError(f"Node {node_id} not found")

    root_title = root_row.get("title") or root_id

    # 2. Get all child nodes (the campaign tree)
    tree_rows = await node_repo.get_node_tree(db, root_id)

    # 3. Count nodes by kind, lifecycle, outcome
    kind_counts: dict[str, int] = {}
    lifecycle_counts: dict[str, int] = {}
    outcome_counts: dict[str, int] = {}

    for row in tree_rows:
        k = row.get("node_type", "untyped")
        kind_counts[k] = kind_counts.get(k, 0) + 1

        lc = row.get("lifecycle", "staged")
        lifecycle_counts[lc] = lifecycle_counts.get(lc, 0) + 1

        oc = row.get("outcome")
        if oc:
            outcome_counts[oc] = outcome_counts.get(oc, 0) + 1

    # 4. Check for the optional campaign config artifact.
    # Contractually this is a JSON artifact with config markers inside
    # payload/metadata, not a dedicated artifact_type enum variant.
    cursor = await db.execute(
        "SELECT artifact_id, artifact_type, payload, metadata FROM artifacts WHERE node_id = ? AND artifact_type = 'json'",
        (root_id,),
    )
    root_artifacts = await cursor.fetchall()
    config_status = (
        "configured"
        if any(_is_campaign_config_artifact(dict(row)) for row in root_artifacts)
        else "not_configured"
    )

    # 5. Get budgets from campaign_budgets table
    budgets = await campaign_repo.list_budgets(db, root_id)

    # 6. Check for campaign_submission_v1 artifacts on child nodes
    submissions: list[dict[str, Any]] = []
    for child in tree_rows:
        if child.get("node_id") == root_id:
            continue
        child_node_id = child.get("node_id")
        if not child_node_id:
            continue
        art_cursor = await db.execute(
            "SELECT * FROM artifacts WHERE node_id = ? AND artifact_type = 'json'",
            (child_node_id,),
        )
        artifacts = await art_cursor.fetchall()
        for art in artifacts:
            meta = _parse_json_field(art["metadata"] if "metadata" in art.keys() else "{}")
            if meta.get("campaign_role") == "submission":
                submissions.append({
                    "node_id": child_node_id,
                    "title": child.get("title"),
                    "owner": child.get("owner_user_id"),
                    "outcome": child.get("outcome"),
                    "artifact_id": art["artifact_id"],
                })

    return {
        "root_node_id": root_id,
        "root_title": root_title,
        "node_count": len(tree_rows),
        "kind_counts": kind_counts,
        "lifecycle_counts": lifecycle_counts,
        "outcome_counts": outcome_counts,
        "budgets": budgets,
        "config_status": config_status,
        "submissions": submissions,
        "submission_count": len(submissions),
        "has_leaderboard": len(submissions) > 0,
    }
