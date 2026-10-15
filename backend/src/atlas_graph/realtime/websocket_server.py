"""
WebSocket server for live graph updates.
- 25s heartbeat
- Subscribe to graph mutations
- Broadcast node changes to connected clients
- Access-controlled: events only reach users who own or have access to the node
- Bounded: per-user and global socket caps; a socket whose send fails is
  evicted immediately instead of lingering until its handler unwinds
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)

# Per-process caps (the manager is process-local, so with two uvicorn workers
# the effective ceiling is twice this). Module constants on purpose - no new
# environment names.
WS_MAX_SOCKETS_PER_USER = 10
WS_MAX_SOCKETS_TOTAL = 2000


class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, list[WebSocket]] = {}  # user_id -> connections
        self._heartbeat_interval = 25
        # id(websocket) -> heartbeat task, so disconnect() can stop it.
        self._heartbeats: dict[int, asyncio.Task[None]] = {}

    def open_connections(self) -> int:
        return sum(len(c) for c in self.active_connections.values())

    def register(self, websocket: WebSocket, user_id: str) -> bool:
        """Track an already-accepted socket and start its heartbeat.

        Returns ``False`` (without registering) when the per-user or global
        cap is reached; the caller closes the socket with 4029.
        """
        if self.open_connections() >= WS_MAX_SOCKETS_TOTAL:
            logger.warning("ws: global socket cap reached (%d)", WS_MAX_SOCKETS_TOTAL)
            return False
        if len(self.active_connections.get(user_id, ())) >= WS_MAX_SOCKETS_PER_USER:
            return False
        self.active_connections.setdefault(user_id, []).append(websocket)
        key = id(websocket)
        task = asyncio.create_task(self._heartbeat(websocket, user_id))
        self._heartbeats[key] = task
        task.add_done_callback(lambda done, key=key: self._forget_heartbeat(key, done))
        return True

    def _forget_heartbeat(self, key: int, task: asyncio.Task[None]) -> None:
        if self._heartbeats.get(key) is task:
            self._heartbeats.pop(key, None)

    async def connect(self, websocket: WebSocket, user_id: str) -> bool:
        await websocket.accept()
        return self.register(websocket, user_id)

    def disconnect(self, websocket: WebSocket, user_id: str):
        if user_id in self.active_connections:
            self.active_connections[user_id] = [
                ws for ws in self.active_connections[user_id] if ws != websocket
            ]
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
        task = self._heartbeats.pop(id(websocket), None)
        if task is not None and not task.done():
            try:
                current = asyncio.current_task()
            except RuntimeError:
                current = None
            if task is not current:
                task.cancel()

    async def broadcast_to_user(self, user_id: str, message: dict):
        """Send a message to all WebSocket connections for a specific user."""
        for ws in list(self.active_connections.get(user_id, [])):
            try:
                await ws.send_json(message)
            except Exception:
                self.disconnect(ws, user_id)

    async def broadcast_graph_event(self, node_id: str, event_type: str, data: dict):
        """Broadcast to users who have access to this node (owner + collaborators).

        Looks up the node's owner and any collaborators via node_access_rules,
        then sends only to those users who are currently connected.
        """
        message = {"type": event_type, "node_id": node_id, "data": data}

        # Determine which connected users should receive this event
        allowed_user_ids = await self._get_allowed_users(node_id)

        for uid in allowed_user_ids:
            for ws in list(self.active_connections.get(uid, [])):
                try:
                    await ws.send_json(message)
                except Exception:
                    self.disconnect(ws, uid)

    async def _get_allowed_users(self, node_id: str) -> set[str]:
        """Return the set of user IDs allowed to receive events for a node.

        Includes the node owner and anyone with a row in node_access_rules.
        Falls back to all connected users only if the DB lookup fails entirely.
        """
        allowed: set[str] = set()
        try:
            from atlas_graph.db.connection import get_db
            from atlas_graph.db.repos import node_repo, access_repo

            async with get_db() as db:
                # Get node owner
                node = await node_repo.get_node(db, node_id)
                if node:
                    owner_id = node.get("owner_user_id")
                    if owner_id:
                        allowed.add(owner_id)

                # Get collaborators from access rules
                rules = await access_repo.get_access_rules(db, node_id)
                for rule in rules:
                    uid = rule.get("user_id")
                    if uid:
                        allowed.add(uid)
        except Exception:
            logger.warning(
                "Failed to look up access for node %s; falling back to owner-only",
                node_id,
                exc_info=True,
            )

        # Only send to users who are actually connected
        return allowed & set(self.active_connections.keys())

    async def _heartbeat(self, websocket: WebSocket, user_id: str):
        try:
            while True:
                await asyncio.sleep(self._heartbeat_interval)
                await websocket.send_json({"type": "heartbeat"})
        except Exception:
            # The peer is gone (or the socket errored): drop it now rather
            # than waiting for the handler's finally, and stop broadcasting
            # into a dead socket.
            self.disconnect(websocket, user_id)

    def get_stats(self) -> dict:
        return {
            "enabled": True,
            "transport": "websocket",
            "heartbeat_seconds": self._heartbeat_interval,
            "connections": {
                "active_users": len(self.active_connections),
                "open_connections": self.open_connections(),
                "max_per_user": WS_MAX_SOCKETS_PER_USER,
                "max_total": WS_MAX_SOCKETS_TOTAL,
            },
        }


manager = ConnectionManager()
