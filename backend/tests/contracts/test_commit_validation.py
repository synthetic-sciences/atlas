"""
Tests for the 5 commit validation rules plus contract warnings at stage time.

Rules:
1. kind != untyped
2. outcome must be set
3. summary must be set
4. insight kind -> insights[] must be non-empty
5. empirical kind -> hypothesis must be non-empty
"""

from __future__ import annotations

from .helpers import commit_node, create_node, update_node


async def test_commit_untyped_fails(client, auth_headers):
    """Committing a node with kind=untyped should fail (409)."""
    node = await create_node(client, auth_headers, title="Untyped")
    nid = node["node_id"]
    rev = node["revision"]

    # Add summary and outcome but leave kind as untyped
    node = await update_node(client, auth_headers, nid, rev, summary="s")
    rev = node["revision"]
    node = await update_node(client, auth_headers, nid, rev, outcome="completed")
    rev = node["revision"]

    result = await commit_node(client, auth_headers, nid, rev)
    assert result is None, "Commit with kind=untyped must fail"


async def test_commit_no_outcome_fails(client, auth_headers):
    """Committing a node without an outcome should fail."""
    node = await create_node(client, auth_headers, title="No Outcome")
    nid = node["node_id"]
    rev = node["revision"]

    node = await update_node(client, auth_headers, nid, rev, kind="insight")
    rev = node["revision"]
    node = await update_node(client, auth_headers, nid, rev, summary="s")
    rev = node["revision"]
    node = await update_node(
        client, auth_headers, nid, rev, insights=["an insight"]
    )
    rev = node["revision"]
    # outcome is never set

    result = await commit_node(client, auth_headers, nid, rev)
    assert result is None, "Commit without outcome must fail"


async def test_commit_no_summary_fails(client, auth_headers):
    """Committing a node without a summary should fail."""
    node = await create_node(client, auth_headers, title="No Summary")
    nid = node["node_id"]
    rev = node["revision"]

    node = await update_node(client, auth_headers, nid, rev, kind="insight")
    rev = node["revision"]
    node = await update_node(client, auth_headers, nid, rev, outcome="completed")
    rev = node["revision"]
    node = await update_node(
        client, auth_headers, nid, rev, insights=["an insight"]
    )
    rev = node["revision"]
    # summary is never set

    result = await commit_node(client, auth_headers, nid, rev)
    assert result is None, "Commit without summary must fail"


async def test_commit_insight_no_insights_fails(client, auth_headers):
    """An insight-kind node with empty insights[] should fail to commit."""
    node = await create_node(client, auth_headers, title="Insight Empty")
    nid = node["node_id"]
    rev = node["revision"]

    node = await update_node(client, auth_headers, nid, rev, kind="insight")
    rev = node["revision"]
    node = await update_node(client, auth_headers, nid, rev, outcome="completed")
    rev = node["revision"]
    node = await update_node(client, auth_headers, nid, rev, summary="s")
    rev = node["revision"]
    # insights is never set (remains [])

    result = await commit_node(client, auth_headers, nid, rev)
    assert result is None, "Insight node with empty insights must fail to commit"


async def test_commit_empirical_no_hypothesis_fails(client, auth_headers):
    """An empirical node without a hypothesis should fail to commit."""
    node = await create_node(client, auth_headers, title="Empirical No Hyp")
    nid = node["node_id"]
    rev = node["revision"]

    node = await update_node(client, auth_headers, nid, rev, kind="empirical")
    rev = node["revision"]
    node = await update_node(client, auth_headers, nid, rev, outcome="completed")
    rev = node["revision"]
    node = await update_node(client, auth_headers, nid, rev, summary="s")
    rev = node["revision"]
    node = await update_node(
        client, auth_headers, nid, rev,
        no_artifacts_reason="no artifacts",
    )
    rev = node["revision"]
    # hypothesis is never set

    result = await commit_node(client, auth_headers, nid, rev)
    assert result is None, "Empirical node without hypothesis must fail to commit"


async def test_contract_warnings_at_stage(client, auth_headers):
    """An empirical + completed node without artifacts should show a contract
    warning when fetched (before commit)."""
    node = await create_node(client, auth_headers, title="Warn Me")
    nid = node["node_id"]
    rev = node["revision"]

    node = await update_node(client, auth_headers, nid, rev, kind="empirical")
    rev = node["revision"]
    node = await update_node(client, auth_headers, nid, rev, outcome="completed")
    rev = node["revision"]

    # Fetch the node to see contract_warnings
    resp = await client.get(f"/api/nodes/{nid}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()

    warnings = data.get("contract_warnings", [])
    assert len(warnings) >= 1
    codes = [w["code"] for w in warnings]
    assert "empirical_completed_requires_artifacts_or_reason" in codes


async def test_successful_insight_commit(client, auth_headers):
    """kind=insight with outcome, summary, and insights[] commits OK."""
    node = await create_node(client, auth_headers, title="Good Insight")
    nid = node["node_id"]
    rev = node["revision"]

    node = await update_node(client, auth_headers, nid, rev, kind="insight")
    rev = node["revision"]
    node = await update_node(client, auth_headers, nid, rev, outcome="completed")
    rev = node["revision"]
    node = await update_node(client, auth_headers, nid, rev, summary="summary")
    rev = node["revision"]
    node = await update_node(
        client, auth_headers, nid, rev, insights=["key finding"]
    )
    rev = node["revision"]

    result = await commit_node(client, auth_headers, nid, rev)
    assert result is not None
    assert result["lifecycle"] == "committed"
    assert result["kind"] == "insight"


async def test_successful_empirical_commit(client, auth_headers):
    """kind=empirical with hypothesis, outcome, summary commits OK
    (using no_artifacts_reason to satisfy the artifact rule)."""
    node = await create_node(client, auth_headers, title="Good Empirical")
    nid = node["node_id"]
    rev = node["revision"]

    node = await update_node(client, auth_headers, nid, rev, kind="empirical")
    rev = node["revision"]
    node = await update_node(client, auth_headers, nid, rev, outcome="completed")
    rev = node["revision"]
    node = await update_node(client, auth_headers, nid, rev, summary="summary")
    rev = node["revision"]
    node = await update_node(
        client, auth_headers, nid, rev, hypothesis="H0: things work"
    )
    rev = node["revision"]
    node = await update_node(
        client, auth_headers, nid, rev, no_artifacts_reason="test only"
    )
    rev = node["revision"]

    result = await commit_node(client, auth_headers, nid, rev)
    assert result is not None
    assert result["lifecycle"] == "committed"
    assert result["kind"] == "empirical"
