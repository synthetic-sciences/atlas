"""
Tests for tag CRUD, assignment, one_only enforcement, and history tracking.
"""

from __future__ import annotations

from .helpers import create_node


async def _create_tag(client, auth_headers, root_node_id, rev, **overrides):
    """Helper: create a tag scoped to the given root node."""
    body = {
        "root_node_id": root_node_id,
        "expected_revision": rev,
        "name": overrides.pop("name", "Test Tag"),
        "bg_color": overrides.pop("bg_color", "#ff0000"),
        "text_color": overrides.pop("text_color", "#ffffff"),
        "one_only": overrides.pop("one_only", False),
        "track_history": overrides.pop("track_history", False),
        **overrides,
    }
    resp = await client.post("/api/tags", json=body, headers=auth_headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_create_tag(client, auth_headers):
    """POST /api/tags creates a tag with the correct fields."""
    root = await create_node(client, auth_headers, title="Tag Root")
    data = await _create_tag(
        client, auth_headers, root["node_id"], root["revision"],
        name="Alpha", bg_color="#123456", text_color="#abcdef",
    )

    tag = data["tag"]
    assert tag["name"] == "Alpha"
    assert tag["bg_color"] == "#123456".upper()
    assert tag["text_color"] == "#ABCDEF"
    assert tag["tag_id"].startswith("tag-")

    # The node revision should have been bumped
    node = data["node"]
    assert node["revision"] == root["revision"] + 1


async def test_all_tag_mutations_reject_stale_revisions(client, auth_headers):
    """Create, update, delete, and assignment writes share the node's OCC
    contract and must never accept a revision that another write consumed."""
    root = await create_node(client, auth_headers, title="Tag OCC Root")
    stale_revision = root["revision"]
    created = await _create_tag(
        client,
        auth_headers,
        root["node_id"],
        stale_revision,
        name="OCC Tag",
    )
    tag_id = created["tag"]["tag_id"]

    stale_create = await client.post(
        "/api/tags",
        json={
            "root_node_id": root["node_id"],
            "expected_revision": stale_revision,
            "name": "Should Not Exist",
        },
        headers=auth_headers,
    )
    stale_update = await client.put(
        "/api/tags",
        json={
            "root_node_id": root["node_id"],
            "tag_id": tag_id,
            "expected_revision": stale_revision,
            "name": "Should Not Win",
        },
        headers=auth_headers,
    )
    stale_assignment = await client.post(
        "/api/tags/assignments",
        json={
            "node_id": root["node_id"],
            "expected_revision": stale_revision,
            "tag_ids": [tag_id],
        },
        headers=auth_headers,
    )
    stale_delete = await client.request(
        "DELETE",
        "/api/tags",
        json={
            "root_node_id": root["node_id"],
            "tag_id": tag_id,
            "expected_revision": stale_revision,
        },
        headers=auth_headers,
    )

    for response in (
        stale_create,
        stale_update,
        stale_assignment,
        stale_delete,
    ):
        assert response.status_code == 409, response.text

    current = await client.get(
        f"/api/nodes/{root['node_id']}",
        headers=auth_headers,
    )
    assert current.status_code == 200
    assert current.json()["revision"] == created["node"]["revision"]


async def test_update_tag(client, auth_headers):
    """PUT /api/tags updates name and color."""
    root = await create_node(client, auth_headers, title="Tag Update Root")
    created = await _create_tag(
        client, auth_headers, root["node_id"], root["revision"],
        name="Before",
    )
    tag_id = created["tag"]["tag_id"]
    node_rev = created["node"]["revision"]

    resp = await client.put(
        "/api/tags",
        json={
            "root_node_id": root["node_id"],
            "tag_id": tag_id,
            "expected_revision": node_rev,
            "name": "After",
            "bg_color": "#000000",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["tag"]["name"] == "After"
    assert data["tag"]["bg_color"] == "#000000"


async def test_delete_tag(client, auth_headers):
    """DELETE /api/tags removes the tag."""
    root = await create_node(client, auth_headers, title="Tag Delete Root")
    created = await _create_tag(
        client, auth_headers, root["node_id"], root["revision"],
        name="Doomed",
    )
    tag_id = created["tag"]["tag_id"]
    node_rev = created["node"]["revision"]

    resp = await client.request(
        "DELETE",
        "/api/tags",
        json={
            "root_node_id": root["node_id"],
            "tag_id": tag_id,
            "expected_revision": node_rev,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 204


async def test_set_tag_assignments(client, auth_headers):
    """POST /api/tags/assignments assigns a tag to a node."""
    root = await create_node(client, auth_headers, title="Assign Root")
    created = await _create_tag(
        client, auth_headers, root["node_id"], root["revision"],
        name="Assignable",
    )
    tag_id = created["tag"]["tag_id"]
    node_rev = created["node"]["revision"]

    # Assign the tag to the root node itself
    resp = await client.post(
        "/api/tags/assignments",
        json={
            "node_id": root["node_id"],
            "expected_revision": node_rev,
            "tag_ids": [tag_id],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()

    # The node should now have the tag in tag_ids
    assert tag_id in data.get("tag_ids", [])


async def test_one_only_enforcement(client, auth_headers):
    """Assigning a one_only tag to node B removes it from node A."""
    root = await create_node(client, auth_headers, title="One Only Root")

    # Create two children via branch
    resp = await client.post(
        "/api/nodes/branch",
        json={
            "node_id": root["node_id"],
            "expected_revision": root["revision"],
            "title": "Node A",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    node_a_id = resp.json()["node"]["node_id"]

    # Re-fetch root revision
    root_resp = await client.get(
        f"/api/nodes/{root['node_id']}", headers=auth_headers
    )
    root_rev = root_resp.json()["revision"]

    resp = await client.post(
        "/api/nodes/branch",
        json={
            "node_id": root["node_id"],
            "expected_revision": root_rev,
            "title": "Node B",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    node_b_id = resp.json()["node"]["node_id"]

    # Re-fetch root revision again
    root_resp = await client.get(
        f"/api/nodes/{root['node_id']}", headers=auth_headers
    )
    root_rev = root_resp.json()["revision"]

    # Create a one_only tag
    tag_data = await _create_tag(
        client, auth_headers, root["node_id"], root_rev,
        name="Exclusive", one_only=True,
    )
    tag_id = tag_data["tag"]["tag_id"]

    # Assign to Node A
    node_a_resp = await client.get(
        f"/api/nodes/{node_a_id}", headers=auth_headers
    )
    node_a_rev = node_a_resp.json()["revision"]

    resp = await client.post(
        "/api/tags/assignments",
        json={
            "node_id": node_a_id,
            "expected_revision": node_a_rev,
            "tag_ids": [tag_id],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert tag_id in resp.json().get("tag_ids", [])

    # Now assign to Node B -- should remove from Node A
    node_b_resp = await client.get(
        f"/api/nodes/{node_b_id}", headers=auth_headers
    )
    node_b_rev = node_b_resp.json()["revision"]

    resp = await client.post(
        "/api/tags/assignments",
        json={
            "node_id": node_b_id,
            "expected_revision": node_b_rev,
            "tag_ids": [tag_id],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert tag_id in resp.json().get("tag_ids", [])

    # Re-fetch Node A to verify tag was removed
    node_a_resp = await client.get(
        f"/api/nodes/{node_a_id}", headers=auth_headers
    )
    assert tag_id not in node_a_resp.json().get("tag_ids", [])
