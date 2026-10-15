import hashlib
import json
import sqlite3
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from atlas_graph.db.connection import get_db
from atlas_graph.integrations.dashboard import Dashboard
from atlas_graph.runtime import Host, configure
from atlas_graph.services import retrieval_service


@pytest.fixture
async def indexing(client):
    service = FastAPI()
    token = uuid4().hex
    state = {"calls": [], "fault": None, "mutate": None}

    @service.post("/api/internal/atlas/index/embeddings")
    async def embed(request: Request):
        assert request.headers["x-atlas-index-token"] == token
        assert "x-atlas-service-token" not in request.headers
        assert "authorization" not in request.headers
        body = await request.json()
        assert set(body) == {"owner_id", "node_id", "revision", "texts"}
        assert 1 <= len(body["texts"]) <= 16
        assert all(len(text) <= 2048 for text in body["texts"])
        state["calls"].append(body)
        if state["mutate"] is not None:
            callback = state["mutate"]
            state["mutate"] = None
            await callback()
        if state["fault"] == "funding":
            raise HTTPException(402, detail={"code": "embedding_funding_unavailable"})
        if state["fault"] == "expired":
            raise HTTPException(410, detail={"code": "embedding_result_expired"})
        if state["fault"] == "redirect":
            return RedirectResponse("http://127.0.0.1/credential-collector")
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "contract": "atlas-index-v1",
                    "model": "openai/text-embedding-3-small",
                    **body,
                },
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        vectors = [[len(text) / 10_000] * 1536 for text in body["texts"]]
        if state["fault"] == "dimension":
            vectors[0] = [1.0]
        if state["fault"] == "nonfinite":
            vectors[0][0] = float("nan")
        if state["fault"] == "boolean":
            vectors[0][0] = True
        payload = {
            "operation_id": "0" * 64 if state["fault"] == "operation" else fingerprint,
            "model": "openai/text-embedding-3-small",
            "vectors": vectors,
            "private_provider_key": "must-not-transfer",
        }
        return Response(json.dumps(payload), media_type="application/json")

    remote = Dashboard(
        "http://127.0.0.1",
        uuid4().hex,
        client=httpx.AsyncClient(transport=httpx.ASGITransport(app=service)),
        index_token=token,
    )
    configure(Host(index=remote.index_node))
    try:
        yield state, remote
    finally:
        configure(Host())
        await remote.close()


async def project(client, title="Indexing"):
    result = await client.post("/api/v1/projects", json={"title": title})
    assert result.status_code == 201, result.text
    return result.json()["project_id"]


async def test_hosted_index_batches_and_binds_vectors_to_exact_node_revision(indexing):
    state, remote = indexing
    node = {"node_id": str(uuid4()), "owner_user_id": str(uuid4()), "revision": 8}
    chunks = [{"text": f"chunk {index}"} for index in range(40)]
    result = await remote.index_node(node, chunks)
    assert len(result) == 40
    assert result == [[len(chunk["text"]) / 10_000] * 1536 for chunk in chunks]
    assert [len(call["texts"]) for call in state["calls"]] == [16, 16, 8]
    assert all(
        call["owner_id"] == node["owner_user_id"]
        and call["node_id"] == node["node_id"]
        and call["revision"] == 8
        for call in state["calls"]
    )


async def test_hosted_index_writes_only_graph_chunks_and_bounds_every_text_field(
    client, indexing
):
    state, _ = indexing
    node = await project(client, "Title " * 1000)
    async with get_db() as db:
        await db.execute(
            "UPDATE nodes SET hypothesis=?,insights=? WHERE node_id=?",
            ("hypothesis " * 600, json.dumps(["insight " * 800]), node),
        )
        await db.commit()
        count = await retrieval_service.embed_node(db, node)
        rows = await db.execute_fetchall(
            "SELECT chunk_text,embedding,metadata FROM knowledge_chunks WHERE node_id=? ORDER BY ordinal",
            (node,),
        )
    assert count == len(rows) > 3
    assert all(len(row["chunk_text"]) <= 2048 for row in rows)
    assert {json.loads(row["metadata"])["field"] for row in rows} == {
        "title_summary",
        "hypothesis",
        "insight",
    }
    assert all(len(json.loads(row["embedding"])) == 1536 for row in rows)
    assert all("must-not-transfer" not in str(dict(row)) for row in rows)
    assert state["calls"]


async def test_index_does_not_publish_stale_vectors_when_node_changes_during_provider_call(
    client, indexing
):
    state, _ = indexing
    node = await project(client, "Old title")
    async with get_db() as db:
        assert await retrieval_service.embed_node(db, node) == 1

    async def mutate():
        async with get_db() as db:
            await db.execute(
                "UPDATE nodes SET title='New title',revision=revision+1 WHERE node_id=?",
                (node,),
            )
            await db.commit()

    state["mutate"] = mutate
    async with get_db() as db:
        assert await retrieval_service.embed_node(db, node) == 0
        assert (
            await db.execute_fetchall(
                "SELECT chunk_text FROM knowledge_chunks WHERE node_id=?", (node,)
            )
        )[0][0] == "Old title"
        assert await retrieval_service.embed_node(db, node) == 1
        assert (
            await db.execute_fetchall(
                "SELECT chunk_text FROM knowledge_chunks WHERE node_id=?", (node,)
            )
        )[0][0] == "New title"


async def test_index_replacement_rolls_back_all_chunks_on_write_failure(
    client, indexing
):
    node = await project(client, "Preserved title")
    async with get_db() as db:
        assert await retrieval_service.embed_node(db, node) == 1
        await db.execute(
            "UPDATE nodes SET title='New title',content='New content' WHERE node_id=?",
            (node,),
        )
        await db.execute(
            "CREATE TRIGGER fixture_index_failure BEFORE INSERT ON knowledge_chunks WHEN NEW.ordinal=1 BEGIN SELECT RAISE(ABORT,'fixture index write failure'); END"
        )
        await db.commit()
        with pytest.raises(sqlite3.IntegrityError, match="fixture index write failure"):
            await retrieval_service.embed_node(db, node)
        rows = await db.execute_fetchall(
            "SELECT chunk_text FROM knowledge_chunks WHERE node_id=? ORDER BY ordinal",
            (node,),
        )
        assert [row[0] for row in rows] == ["Preserved title"]


@pytest.mark.parametrize(
    "fault", ["operation", "dimension", "nonfinite", "boolean", "funding", "expired", "redirect"]
)
async def test_hosted_index_rejects_invalid_or_unfunded_result_before_changing_graph(
    client, indexing, fault
):
    state, _ = indexing
    node = await project(client)
    state["fault"] = fault
    async with get_db() as db:
        with pytest.raises(HTTPException) as refused:
            await retrieval_service.embed_node(db, node)
        assert refused.value.status_code == {"funding": 402, "expired": 410}.get(fault, 503)
        assert not await db.execute_fetchall(
            "SELECT * FROM knowledge_chunks WHERE node_id=?", (node,)
        )
        assert not await db.execute_fetchall(
            "SELECT * FROM knowledge_sources WHERE external_ref=?", (node,)
        )
    assert len(state["calls"]) == 1
