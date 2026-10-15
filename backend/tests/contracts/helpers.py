from httpx import AsyncClient


async def create_node(
    client: AsyncClient, headers: dict, title: str = "Test Node", **kwargs
) -> dict:
    """Helper: create a node via the API and return the response JSON."""
    body = {"title": title, **kwargs}
    resp = await client.post("/api/nodes/stage-create", json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def update_node(
    client: AsyncClient,
    headers: dict,
    node_id: str,
    expected_revision: int,
    **fields,
) -> dict:
    """Helper: stage-update a node and return the response JSON."""
    body = {"node_id": node_id, "expected_revision": expected_revision, **fields}
    resp = await client.post("/api/nodes/stage-update", json=body, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def commit_node(
    client: AsyncClient,
    headers: dict,
    node_id: str,
    expected_revision: int,
    summary: str | None = None,
) -> dict | None:
    """Helper: commit a node. Returns JSON on success, None on validation failure."""
    body = {"node_id": node_id, "expected_revision": expected_revision}
    if summary is not None:
        body["summary"] = summary
    resp = await client.post("/api/nodes/commit", json=body, headers=headers)
    if resp.status_code == 409:
        return None
    assert resp.status_code == 200, resp.text
    return resp.json()


async def create_committed_node(
    client: AsyncClient,
    headers: dict,
    title: str = "Committed Node",
    kind: str = "empirical",
    outcome: str = "completed",
    summary: str = "A test summary",
    hypothesis: str = "A hypothesis",
    no_artifacts_reason: str = "Test -- no artifacts needed",
) -> dict:
    """Helper: create a fully committed empirical node in one shot."""
    node = await create_node(client, headers, title=title)
    node_id = node["node_id"]
    rev = node["revision"]

    # Set kind
    node = await update_node(client, headers, node_id, rev, kind=kind)
    rev = node["revision"]

    # Set outcome
    node = await update_node(client, headers, node_id, rev, outcome=outcome)
    rev = node["revision"]

    # Set summary
    node = await update_node(client, headers, node_id, rev, summary=summary)
    rev = node["revision"]

    # Set hypothesis (empirical) or insights (insight)
    if kind == "empirical":
        node = await update_node(
            client, headers, node_id, rev, hypothesis=hypothesis
        )
        rev = node["revision"]
        node = await update_node(
            client, headers, node_id, rev,
            no_artifacts_reason=no_artifacts_reason,
        )
        rev = node["revision"]
    elif kind == "insight":
        node = await update_node(
            client, headers, node_id, rev, insights=["insight 1"]
        )
        rev = node["revision"]

    # Commit
    result = await commit_node(client, headers, node_id, rev)
    assert result is not None, "Commit should succeed for a fully prepared node"
    return result
