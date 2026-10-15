"""
Tests for the artifact upload pipeline: prepare -> upload -> finalize,
plus list and delete.
"""

from __future__ import annotations

from .helpers import create_node


async def test_prepare_upload(client, auth_headers):
    """POST /api/artifacts/prepare returns a batch_token and upload URLs."""
    node = await create_node(client, auth_headers, title="Artifact Node")

    resp = await client.post(
        "/api/artifacts/prepare",
        json={
            "node_id": node["node_id"],
            "expected_revision": node["revision"],
            "items": [
                {
                    "artifact_type": "text",
                    "filename": "results.txt",
                    "media_type": "text/plain",
                    "title": "Results",
                }
            ],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()

    assert "batch_token" in data
    assert "expires_at" in data
    assert len(data["items"]) == 1

    item = data["items"][0]
    assert "upload_id" in item
    assert "upload_url" in item
    assert item["method"] == "PUT"


async def test_finalize_upload(client, auth_headers):
    """Finalize creates artifact records and bumps revision once."""
    node = await create_node(client, auth_headers, title="Finalize Node")
    node_id = node["node_id"]
    rev_before = node["revision"]

    # Prepare
    prep_resp = await client.post(
        "/api/artifacts/prepare",
        json={
            "node_id": node_id,
            "expected_revision": rev_before,
            "items": [
                {
                    "artifact_type": "text",
                    "filename": "data.txt",
                    "media_type": "text/plain",
                    "title": "Data File",
                },
                {
                    "artifact_type": "json",
                    "filename": "config.json",
                    "media_type": "application/json",
                    "title": "Config",
                },
            ],
        },
        headers=auth_headers,
    )
    assert prep_resp.status_code == 201
    prep_data = prep_resp.json()
    batch_token = prep_data["batch_token"]

    # Upload files
    for item in prep_data["items"]:
        upload_id = item["upload_id"]
        resp = await client.put(
            f"/api/artifacts/upload/{upload_id}",
            content=b"test file content",
            headers={
                **auth_headers,
                "Content-Type": "text/plain",
                "X-Filename": "test.txt",
            },
        )
        assert resp.status_code == 200

    # Finalize
    fin_resp = await client.post(
        "/api/artifacts/finalize",
        json={"node_id": node_id, "batch_token": batch_token},
        headers=auth_headers,
    )
    assert fin_resp.status_code == 200
    fin_data = fin_resp.json()

    # Revision should have bumped by exactly 1 (single bump for entire batch)
    assert fin_data["revision"] == rev_before + 1


async def test_list_artifacts(client, auth_headers):
    """GET /api/artifacts/{node_id} returns the artifact list."""
    node = await create_node(client, auth_headers, title="List Artifacts Node")
    node_id = node["node_id"]

    # Prepare + upload + finalize one artifact
    prep_resp = await client.post(
        "/api/artifacts/prepare",
        json={
            "node_id": node_id,
            "expected_revision": node["revision"],
            "items": [
                {
                    "artifact_type": "text",
                    "filename": "output.txt",
                    "media_type": "text/plain",
                    "title": "Output",
                }
            ],
        },
        headers=auth_headers,
    )
    assert prep_resp.status_code == 201
    prep_data = prep_resp.json()

    for item in prep_data["items"]:
        await client.put(
            f"/api/artifacts/upload/{item['upload_id']}",
            content=b"output data",
            headers={
                **auth_headers,
                "Content-Type": "text/plain",
                "X-Filename": "output.txt",
            },
        )

    await client.post(
        "/api/artifacts/finalize",
        json={"node_id": node_id, "batch_token": prep_data["batch_token"]},
        headers=auth_headers,
    )

    # Now list
    resp = await client.get(f"/api/artifacts/{node_id}", headers=auth_headers)
    assert resp.status_code == 200
    artifacts = resp.json()

    assert isinstance(artifacts, list)
    assert len(artifacts) == 1
    assert artifacts[0]["title"] == "Output"
    assert artifacts[0]["artifact_type"] == "text"


async def test_delete_artifact(client, auth_headers):
    """DELETE /api/artifacts/{node_id}/{artifact_id} removes the artifact."""
    node = await create_node(client, auth_headers, title="Delete Artifact Node")
    node_id = node["node_id"]

    # Prepare + upload + finalize
    prep_resp = await client.post(
        "/api/artifacts/prepare",
        json={
            "node_id": node_id,
            "expected_revision": node["revision"],
            "items": [
                {
                    "artifact_type": "text",
                    "filename": "doomed.txt",
                    "media_type": "text/plain",
                    "title": "Doomed",
                }
            ],
        },
        headers=auth_headers,
    )
    assert prep_resp.status_code == 201
    prep_data = prep_resp.json()

    for item in prep_data["items"]:
        await client.put(
            f"/api/artifacts/upload/{item['upload_id']}",
            content=b"doomed data",
            headers={
                **auth_headers,
                "Content-Type": "text/plain",
                "X-Filename": "doomed.txt",
            },
        )

    await client.post(
        "/api/artifacts/finalize",
        json={"node_id": node_id, "batch_token": prep_data["batch_token"]},
        headers=auth_headers,
    )

    # Get artifact ID
    list_resp = await client.get(
        f"/api/artifacts/{node_id}", headers=auth_headers
    )
    artifact_id = list_resp.json()[0]["artifact_id"]

    # Delete
    del_resp = await client.delete(
        f"/api/artifacts/{node_id}/{artifact_id}", headers=auth_headers
    )
    assert del_resp.status_code == 204

    # Verify it is gone
    list_resp2 = await client.get(
        f"/api/artifacts/{node_id}", headers=auth_headers
    )
    assert len(list_resp2.json()) == 0
