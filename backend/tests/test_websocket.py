from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


@pytest.fixture
def sockets(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ATLAS_MODE", "local")
    monkeypatch.delenv("ATLAS_DATABASE_URL", raising=False)
    monkeypatch.delenv("ATLAS_LOCAL_TOKEN", raising=False)
    from atlas_graph.main import app

    with TestClient(
        app, base_url="http://127.0.0.1", headers={"Authorization": "Bearer local"}
    ) as client:
        yield client


def test_socket_auth_acl_ping_and_normal_disconnect(sockets):
    project = sockets.post("/api/v1/projects", json={"title": "Live graph"}).json()[
        "project_id"
    ]
    with sockets.websocket_connect("/api/ws") as socket:
        socket.send_json({"type": "auth", "token": "local"})
        assert socket.receive_json()["type"] == "connected"
        socket.send_json({"type": "subscribe", "node_id": project})
        assert socket.receive_json() == {"type": "subscribed", "node_id": project}
        absent = str(uuid4())
        socket.send_json({"type": "subscribe", "node_id": absent})
        assert socket.receive_json() == {
            "type": "error",
            "code": "access_denied",
            "node_id": absent,
        }
        socket.send_json({"type": "ping"})
        assert socket.receive_json() == {"type": "pong"}
    from atlas_graph.realtime.websocket_server import manager

    assert manager.open_connections() == 0


@pytest.mark.parametrize(
    "frame", [[], {"type": "auth", "token": "invalid"}, {"type": "ping"}]
)
def test_socket_rejects_invalid_auth_frames(sockets, frame):
    with sockets.websocket_connect("/api/ws") as socket:
        socket.send_json(frame)
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()
        assert closed.value.code == 4001


@pytest.mark.parametrize(
    "path,headers",
    [("/api/ws?token=local", {}), ("/api/ws", {"Origin": "https://example.com"})],
)
def test_socket_rejects_query_tokens_and_foreign_origins(sockets, path, headers):
    with sockets.websocket_connect(path, headers=headers) as socket:
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()
        assert closed.value.code == 4001


async def test_child_events_follow_current_inherited_access_and_fail_closed(
    client, monkeypatch
):
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from atlas_graph.db.connection import get_db
    from atlas_graph.db.repos import access_repo
    from atlas_graph.realtime.websocket_server import ConnectionManager

    root = (
        await client.post("/api/v1/projects", json={"title": "Shared graph"})
    ).json()["project_id"]
    viewer, other, child, otherroot = [str(uuid4()) for _ in range(4)]
    now = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        owner = (
            await (
                await db.execute(
                    "SELECT owner_user_id FROM nodes WHERE node_id=?", (root,)
                )
            ).fetchone()
        )[0]
        for actor in (viewer, other):
            await db.execute(
                "INSERT INTO users (user_id,email,created_at,updated_at) VALUES (?,?,?,?)",
                (actor, f"{actor}@atlas.invalid", now, now),
            )
        for node, actor in ((child, other), (otherroot, other)):
            await db.execute(
                "INSERT INTO nodes (node_id,owner_user_id,title,created_at,updated_at) VALUES (?,?,?,?,?)",
                (node, actor, "Nested", now, now),
            )
        for parent in (root, otherroot):
            await db.execute(
                "INSERT INTO node_edges (parent_id,child_id,created_at) VALUES (?,?,?)",
                (parent, child, now),
            )
        await db.commit()
        await access_repo.set_access_rule(
            db, node_id=root, user_id=viewer, access_level="USER"
        )
    manager = ConnectionManager()
    received = {actor: [] for actor in (owner, viewer, other, str(uuid4()))}
    for actor, messages in received.items():

        async def send(message, messages=messages):
            messages.append(message)

        manager.active_connections[actor] = [SimpleNamespace(send_json=send)]
    await manager.broadcast_graph_event(child, "node_mutated", {"title": "First"})
    assert {actor for actor, messages in received.items() if messages} == {
        owner,
        viewer,
        other,
    }
    async with get_db() as db:
        await access_repo.remove_access_rule(db, root, viewer)
    await manager.broadcast_graph_event(child, "node_mutated", {"title": "Second"})
    assert len(received[viewer]) == 1
    assert len(received[owner]) == 2
    from atlas_graph.db.repos import node_repo

    async def failed(*args):
        raise RuntimeError("Database unavailable")

    monkeypatch.setattr(node_repo, "find_root_node_ids", failed)
    await manager.broadcast_graph_event(child, "node_mutated", {"title": "Unavailable"})
    assert len(received[owner]) == 2
