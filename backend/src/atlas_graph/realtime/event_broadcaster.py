"""Hook into service layer to broadcast events."""
from atlas_graph.realtime.websocket_server import manager


async def on_node_mutated(node_id: str, operation: str, node_data: dict):
    await manager.broadcast_graph_event(node_id, "node_mutated", {
        "operation": operation,
        **node_data,
    })


async def on_node_deleted(node_id: str):
    await manager.broadcast_graph_event(node_id, "node_deleted", {"node_id": node_id})


async def on_lease_mutated(user_id: str, lease_id: str, operation: str, lease_data: dict):
    """Broadcast a lease state change to the owning user's WebSocket connections.

    Leases are user-scoped (unlike nodes, which have sharing/ACL), so we fan out
    only to the owner. ``operation`` is one of ``acquired|status_changed|released``.
    """
    await manager.broadcast_to_user(user_id, {
        "type": "lease_mutated",
        "lease_id": lease_id,
        "data": {"operation": operation, **lease_data},
    })
