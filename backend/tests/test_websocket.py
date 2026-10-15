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

    with TestClient(app, base_url="http://127.0.0.1", headers={"Authorization": "Bearer local"}) as client:
        yield client


def test_socket_auth_acl_ping_and_normal_disconnect(sockets):
    project = sockets.post("/api/v1/projects", json={"title": "Live graph"}).json()["project_id"]
    with sockets.websocket_connect("/api/ws") as socket:
        socket.send_json({"type": "auth", "token": "local"})
        assert socket.receive_json()["type"] == "connected"
        socket.send_json({"type": "subscribe", "node_id": project})
        assert socket.receive_json() == {"type": "subscribed", "node_id": project}
        absent = str(uuid4())
        socket.send_json({"type": "subscribe", "node_id": absent})
        assert socket.receive_json() == {"type": "error", "code": "access_denied", "node_id": absent}
        socket.send_json({"type": "ping"})
        assert socket.receive_json() == {"type": "pong"}
    from atlas_graph.realtime.websocket_server import manager

    assert manager.open_connections() == 0


@pytest.mark.parametrize("frame", [[], {"type": "auth", "token": "invalid"}, {"type": "ping"}])
def test_socket_rejects_invalid_auth_frames(sockets, frame):
    with sockets.websocket_connect("/api/ws") as socket:
        socket.send_json(frame)
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()
        assert closed.value.code == 4001


@pytest.mark.parametrize("path,headers", [("/api/ws?token=local", {}), ("/api/ws", {"Origin": "https://example.com"})])
def test_socket_rejects_query_tokens_and_foreign_origins(sockets, path, headers):
    with sockets.websocket_connect(path, headers=headers) as socket:
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()
        assert closed.value.code == 4001
