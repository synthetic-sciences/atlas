"""
Tests for the full node lifecycle: create -> update -> commit -> branch -> delete.
"""

from __future__ import annotations

from .helpers import (
    commit_node,
    create_committed_node,
    create_node,
    update_node,
)


async def test_create_node(client, auth_headers):
    """stage_create returns a node at revision 0 with lifecycle=staged."""
    node = await create_node(client, auth_headers, title="My Node")

    assert node["node_id"]
    assert node["title"] == "My Node"
    assert node["revision"] == 0
    assert node["lifecycle"] == "staged"
    assert node["kind"] == "untyped"


async def test_update_node(client, auth_headers):
    """stage_update increments the revision."""
    node = await create_node(client, auth_headers, title="Rev Test")
    assert node["revision"] == 0

    updated = await update_node(
        client, auth_headers, node["node_id"], 0, title="Rev Test Updated"
    )
    assert updated["revision"] == 1
    assert updated["title"] == "Rev Test Updated"


async def test_commit_node(client, auth_headers):
    """commit returns a node with lifecycle=committed."""
    result = await create_committed_node(client, auth_headers)

    assert result["lifecycle"] == "committed"
    assert result["kind"] == "empirical"
    assert result["outcome"] == "completed"


async def test_branch_node(client, auth_headers):
    """Branching creates a child and bumps the parent revision."""
    parent = await create_node(client, auth_headers, title="Branch Parent")
    parent = await update_node(
        client,
        auth_headers,
        parent["node_id"],
        parent["revision"],
        content="seed content",
        repo_url="https://github.com/acme/widgets",
        branch_name="main",
        head_commit_sha="abc123",
    )
    parent_id = parent["node_id"]
    parent_rev = parent["revision"]

    resp = await client.post(
        "/api/nodes/branch",
        json={
            "node_id": parent_id,
            "expected_revision": parent_rev,
            "title": "Branch Child",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()

    child = data["node"]
    assert child["title"] == "Branch Child"
    assert child["revision"] == 0
    assert child["lifecycle"] == "staged"
    assert child["content"] == "seed content"
    assert child["repo_url"] == "https://github.com/acme/widgets"
    assert child["branch_name"] == "main"
    assert child["head_commit_sha"] == "abc123"

    # Parent revision should have been bumped
    assert data["parent_revision"] == parent_rev + 1

    # Child should have the parent in its parent_ids
    child_parent_ids = child.get("parent_ids", [])
    # parent_ids may be full dicts or just strings depending on implementation
    if child_parent_ids and isinstance(child_parent_ids[0], dict):
        actual_ids = [p["node_id"] for p in child_parent_ids]
    else:
        actual_ids = child_parent_ids
    assert parent_id in actual_ids


async def test_delete_node(client, auth_headers):
    """After deleting a node, GET returns 404."""
    node = await create_node(client, auth_headers, title="Delete Me")
    node_id = node["node_id"]

    resp = await client.delete(
        f"/api/nodes/{node_id}",
        headers=auth_headers,
    )
    assert resp.status_code == 204

    # Trying to GET the deleted node should fail
    resp = await client.get(f"/api/nodes/{node_id}", headers=auth_headers)
    assert resp.status_code == 404


async def test_full_lifecycle(client, auth_headers):
    """create -> update kind/outcome/summary/insights -> commit -> branch -> delete."""
    # 1. Create
    node = await create_node(client, auth_headers, title="Full Lifecycle")
    nid = node["node_id"]
    rev = node["revision"]
    assert rev == 0

    # 2. Update kind
    node = await update_node(client, auth_headers, nid, rev, kind="insight")
    rev = node["revision"]
    assert node["kind"] == "insight"

    # 3. Update outcome
    node = await update_node(client, auth_headers, nid, rev, outcome="completed")
    rev = node["revision"]
    assert node["outcome"] == "completed"

    # 4. Update summary
    node = await update_node(
        client, auth_headers, nid, rev, summary="Test summary"
    )
    rev = node["revision"]
    assert node["summary"] == "Test summary"

    # 5. Update insights
    node = await update_node(
        client, auth_headers, nid, rev, insights=["key insight"]
    )
    rev = node["revision"]
    assert node["insights"] == ["key insight"]

    # 6. Commit
    result = await commit_node(client, auth_headers, nid, rev)
    assert result is not None
    assert result["lifecycle"] == "committed"
    rev = result["revision"]

    # 7. Branch
    resp = await client.post(
        "/api/nodes/branch",
        json={"node_id": nid, "expected_revision": rev, "title": "Child"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    child_id = resp.json()["node"]["node_id"]

    # 8. Delete child
    resp = await client.delete(f"/api/nodes/{child_id}", headers=auth_headers)
    assert resp.status_code == 204
