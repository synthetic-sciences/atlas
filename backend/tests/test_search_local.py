from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from atlas_graph.db.connection import get_db
from atlas_graph.db.repos import access_repo
from atlas_graph.runtime import Host, configure
from atlas_graph.services.retrieval_service import _node_source_id


async def test_sqlite_search_uses_text_and_graph_access_without_a_paid_embedding(
    client,
):
    owned = (
        await client.post("/api/v1/projects", json={"title": "Local evidence"})
    ).json()["project_id"]
    stranger, private, child = str(uuid4()), str(uuid4()), str(uuid4())
    now = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        owner = (
            await (
                await db.execute(
                    "SELECT owner_user_id FROM nodes WHERE node_id=?", (owned,)
                )
            ).fetchone()
        )[0]
        await db.execute(
            "INSERT INTO users (user_id,email,created_at,updated_at) VALUES (?,?,?,?)",
            (stranger, f"{stranger}@atlas.invalid", now, now),
        )
        for node in (private, child):
            await db.execute(
                "INSERT INTO nodes (node_id,owner_user_id,title,created_at,updated_at) VALUES (?,?,?,?,?)",
                (node, stranger, "Private graph", now, now),
            )
        await db.execute(
            "INSERT INTO node_edges (parent_id,child_id,created_at) VALUES (?,?,?)",
            (private, child, now),
        )
        for node, actor, text in [
            (owned, owner, "Owner evidence"),
            (private, stranger, "Private evidence"),
            (child, stranger, "Nested evidence"),
        ]:
            source = await _node_source_id(db, node, actor)
            await db.execute(
                "INSERT INTO knowledge_chunks (chunk_id,source_id,node_id,chunk_text,ordinal) VALUES (?,?,?,?,0)",
                (str(uuid4()), source, node, text),
            )
        await db.commit()
    paid = []

    async def embed(text):
        paid.append(text)
        raise AssertionError("SQLite text retrieval must not call a managed provider")

    configure(Host(query=lambda request: SimpleNamespace(embed=embed)))
    try:
        response = await client.post(
            "/api/knowledge/search", json={"query": "evidence"}
        )
        assert response.status_code == 200, response.text
        assert {item["node_id"] for item in response.json()["results"]} == {owned}
        assert response.json()["query_embedding_id"] is None
        assert paid == []
        async with get_db() as db:
            await access_repo.set_access_rule(
                db, node_id=private, user_id=owner, access_level="USER"
            )
        shared = await client.post(
            "/api/knowledge/search", json={"query": "evidence", "k": 10}
        )
        assert shared.status_code == 200, shared.text
        assert {item["node_id"] for item in shared.json()["results"]} == {
            owned,
            private,
            child,
        }
        async with get_db() as db:
            await db.execute(
                "DELETE FROM node_access_rules WHERE node_id=? AND user_id=?",
                (private, owner),
            )
            await db.commit()
        revoked = await client.post("/api/knowledge/search", json={"query": "evidence"})
        assert {item["node_id"] for item in revoked.json()["results"]} == {owned}
        assert paid == []
    finally:
        configure(Host())
