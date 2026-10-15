import hashlib
import json
from uuid import uuid4

import httpx
import pytest

from fastapi import HTTPException
from starlette.requests import Request

from atlas_graph.integrations.dashboard import Dashboard
from atlas_graph.runtime import Host, configure


@pytest.fixture
async def query_service(client):
    calls = []
    state = {"fault": None}
    account_token = uuid4().hex

    def respond(request):
        assert (
            str(request.url)
            == "https://dashboard.example/api/internal/atlas/query/embeddings"
        )
        assert request.headers["x-atlas-service-token"] == account_token
        assert request.headers["authorization"] == "Bearer local"
        assert request.headers["x-organization-id"] == "selected-workspace"
        assert "x-atlas-index-token" not in request.headers
        assert "x-private-key" not in request.headers
        body = json.loads(request.content)
        assert set(body) == {"request_id", "text"}
        calls.append(body)
        fault = state["fault"]
        if isinstance(fault, int):
            return httpx.Response(
                fault, json={"detail": {"code": "embedding_outcome_pending"}}
            )
        if fault == "redirect":
            return httpx.Response(
                302, headers={"Location": "https://collector.example"}
            )
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "contract": "atlas-query-v1",
                    "model": "openai/text-embedding-3-small",
                    **body,
                },
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        vector = [0.1] * 1536
        if fault == "dimension":
            vector = [0.1]
        if fault == "boolean":
            vector[0] = True
        if fault == "nonfinite":
            vector[0] = float("nan")
        return httpx.Response(
            200,
            content=json.dumps(
                {
                    "operation_id": "a" * 64,
                    "request_hash": "0" * 64 if fault == "fingerprint" else fingerprint,
                    "model": "other"
                    if fault == "model"
                    else "openai/text-embedding-3-small",
                    "vectors": [vector, vector] if fault == "count" else [vector],
                }
            ),
        )

    remote = Dashboard(
        "https://dashboard.example",
        account_token,
        client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    configure(Host(query=remote.query))
    try:
        yield calls, state, remote
    finally:
        configure(Host())
        await remote.close()


async def search(remote, **kwargs):
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/knowledge/search",
            "query_string": b"",
            "headers": [
                (key.lower().encode(), value.encode())
                for key, value in {
                    "Authorization": "Bearer local",
                    "X-Organization-ID": "selected-workspace",
                    "X-Private-Key": "must-not-forward",
                    **kwargs,
                }.items()
            ],
        }
    )
    return await remote.query(request).embed("Evidence")


async def test_hosted_query_passes_only_request_credentials_and_reuses_query_id(
    client, query_service
):
    calls, _, remote = query_service
    for _ in range(2):
        result = await search(remote, **{"Idempotency-Key": "stable-query"})
        assert result == ([0.1] * 1536, None)
    assert len(calls) == 2
    assert calls[0] == calls[1]
    await search(remote)
    await search(remote)
    assert calls[2]["request_id"] != calls[3]["request_id"]


@pytest.mark.parametrize("status", [401, 402, 403, 409, 410, 429, 503])
async def test_hosted_query_preserves_account_errors_without_silent_degradation(
    client, query_service, status
):
    _, state, remote = query_service
    state["fault"] = status
    with pytest.raises(HTTPException) as error:
        await search(remote)
    assert error.value.status_code == status


@pytest.mark.parametrize(
    "fault",
    ["redirect", "dimension", "boolean", "nonfinite", "fingerprint", "model", "count"],
)
async def test_hosted_query_fails_closed_on_invalid_or_unbound_response(
    client, query_service, fault
):
    calls, state, remote = query_service
    state["fault"] = fault
    with pytest.raises(HTTPException) as error:
        await search(remote)
    assert error.value.status_code == 503
    assert len(calls) == 1


async def test_graph_disabled_search_does_not_dispatch_paid_query(
    client, query_service
):
    calls, _, remote = query_service
    response = await client.post(
        "/api/knowledge/search", json={"query": "Evidence", "include_graph": False}
    )
    assert response.status_code == 200 and response.json()["results"] == []
    assert calls == []
