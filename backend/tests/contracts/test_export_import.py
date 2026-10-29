"""
Tests for export/import round-trip: nodes exported with API-facing field names,
imported with fresh IDs.
"""

from __future__ import annotations

import json

from atlas_graph.db.connection import get_db
from .helpers import create_node


async def test_export_uses_api_names(client, auth_headers):
    """Exported nodes use kind, parent_ids, child_ids (API-facing names)."""
    root = await create_node(client, auth_headers, title="Export Root")

    # Branch a child so we have edges to export
    resp = await client.post(
        "/api/nodes/branch",
        json={
            "node_id": root["node_id"],
            "expected_revision": root["revision"],
            "title": "Export Child",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    child_id = resp.json()["node"]["node_id"]

    # Export both nodes
    export_resp = await client.post(
        "/api/export/subgraph",
        json={"node_ids": [root["node_id"]]},
        headers=auth_headers,
    )
    assert export_resp.status_code == 200
    data = export_resp.json()

    assert data["version"] == 2
    assert data["node_count"] >= 2

    # Check that export uses stable interchange field names.
    for node in data["nodes"]:
        assert "node_type" in node, "Export should use interchange field name 'node_type'"
        assert "incoming_ids" in node, "Export should use 'incoming_ids' not 'parent_ids'"
        assert "outgoing_ids" in node, "Export should use 'outgoing_ids' not 'child_ids'"
        # API-facing aliases should NOT be present in export
        assert "kind" not in node
        assert "parent_ids" not in node
        assert "child_ids" not in node


async def test_import_round_trip(client, auth_headers):
    """Export -> import -> nodes exist with new IDs."""
    # Create a small graph
    root = await create_node(client, auth_headers, title="RT Root")
    async with get_db() as db:
        await db.execute(
            """
            UPDATE nodes
            SET repo_url = ?, branch_name = ?, head_commit_sha = ?, run_data = ?, semantic_data = ?
            WHERE node_id = ?
            """,
            (
                "https://github.com/acme/widgets",
                "main",
                "abc123",
                json.dumps({"config": {"lr": 1e-3}}),
                json.dumps({"code_state": {"pinned_tag": "atlas/root-r0", "pinned_sha": "abc123"}}),
                root["node_id"],
            ),
        )
        await db.commit()

    resp = await client.post(
        "/api/nodes/branch",
        json={
            "node_id": root["node_id"],
            "expected_revision": root["revision"],
            "title": "RT Child",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    child_id = resp.json()["node"]["node_id"]

    # Export
    export_resp = await client.post(
        "/api/export/subgraph",
        json={"node_ids": [root["node_id"]]},
        headers=auth_headers,
    )
    assert export_resp.status_code == 200
    export_data = export_resp.json()

    # Import
    import_resp = await client.post(
        "/api/import/subgraph",
        json=export_data,
        headers=auth_headers,
    )
    assert import_resp.status_code == 201
    import_data = import_resp.json()

    assert import_data["imported_count"] >= 2

    id_mapping = import_data["id_mapping"]
    assert root["node_id"] in id_mapping
    assert child_id in id_mapping

    # New IDs should be different from old IDs
    for old_id, new_id in id_mapping.items():
        assert old_id != new_id

    # Verify imported nodes exist
    for old_id, new_id in id_mapping.items():
        resp = await client.get(f"/api/nodes/{new_id}", headers=auth_headers)
        assert resp.status_code == 200, (
            f"Imported node {new_id} (from {old_id}) should exist"
        )
    async with get_db() as db:
        cur = await db.execute(
            "SELECT repo_url, branch_name, head_commit_sha, run_data, semantic_data FROM nodes WHERE node_id = ?",
            (id_mapping[root["node_id"]],),
        )
        row = dict(await cur.fetchone())
    assert row["repo_url"] == "https://github.com/acme/widgets"
    assert row["branch_name"] == "main"
    assert row["head_commit_sha"] == "abc123"
    assert json.loads(row["run_data"])["config"]["lr"] == 1e-3
    assert json.loads(row["semantic_data"])["code_state"]["pinned_tag"] == "atlas/root-r0"


async def test_export_summary_pdf_returns_pdf_bytes(client, auth_headers):
    """The dashboard summary PDF renders off the event loop and stays a PDF."""
    root = await create_node(client, auth_headers, title="PDF Root")
    resp = await client.post(
        "/api/export/summary/pdf",
        json={"node_ids": [root["node_id"]]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF")


async def test_cli_export_summary_pdf_routes_return_pdf_bytes(client, auth_headers):
    """Both compatibility CLI summary routes render through the threadpool."""
    root = await create_node(client, auth_headers, title="CLI PDF Root")
    summary = await client.post(
        "/api/v1/export-summary-pdf",
        json={"node_ids": [root["node_id"]]},
        headers=auth_headers,
    )
    assert summary.status_code == 200, summary.text
    assert summary.headers["content-type"] == "application/pdf"
    assert summary.content.startswith(b"%PDF")

    rendered = await client.post(
        "/api/v1/export-summary-render-pdf",
        json={"markdown": "# Rendered\n\nBody text.", "title": "Rendered"},
        headers=auth_headers,
    )
    assert rendered.status_code == 200, rendered.text
    assert rendered.headers["content-type"] == "application/pdf"
    assert rendered.content.startswith(b"%PDF")
