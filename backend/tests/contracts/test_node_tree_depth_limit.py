from __future__ import annotations

from typing import Any

from atlas_graph.db.repos import edge_repo, node_repo
from atlas_graph.services import node_service


class _CountingDb:
    """Transparent connection proxy that counts database round trips."""

    def __init__(self, db: Any) -> None:
        self._db = db
        self.execute_count = 0
        self.executed_sql: list[str] = []

    async def execute(self, *args: Any, **kwargs: Any):
        self.execute_count += 1
        self.executed_sql.append(str(args[0]))
        return await self._db.execute(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._db, name)


async def _node(db: Any, user_id: str, node_id: str) -> None:
    await node_repo.create_node(
        db,
        node_id=node_id,
        owner_user_id=user_id,
        title=node_id,
    )


async def test_depth_limited_tree_is_batched_and_root_anchored(db_with_user):
    db, user_id = db_with_user
    node_ids = ["root", *(f"node-{index:02d}" for index in range(1, 15))]
    for node_id in node_ids:
        await _node(db, user_id, node_id)

    # Complete binary tree with four levels (depths 0 through 3).
    for index, node_id in enumerate(node_ids[1:], start=1):
        parent_id = node_ids[(index - 1) // 2]
        await edge_repo.add_edge(db, parent_id, node_id)

    counted = _CountingDb(db)
    result = await node_service.get_node_tree(
        counted,
        user_id,
        node_ids[-1],
        max_depth=3,
    )

    assert [node["node_id"] for node in result["nodes"]] == node_ids
    assert result["root_node_ids"] == ["root"]
    # Access check + root lookup + root read + one read per depth + edge read.
    # The former Python BFS needed 25 reads for this same tree.
    assert counted.execute_count == 7


async def test_depth_limited_tree_collapses_dag_paths_and_honors_cap(db_with_user):
    db, user_id = db_with_user
    for node_id in ("root", "a", "b", "shared"):
        await _node(db, user_id, node_id)

    await edge_repo.add_edge(db, "root", "a")
    await edge_repo.add_edge(db, "root", "b")
    await edge_repo.add_edge(db, "a", "shared")
    await edge_repo.add_edge(db, "b", "shared")

    result = await node_service.get_node_tree(
        db,
        user_id,
        "root",
        max_depth=2,
        max_nodes=3,
    )

    node_ids = [node["node_id"] for node in result["nodes"]]
    assert node_ids == ["root", "a", "b"]
    assert len(node_ids) == len(set(node_ids))


async def test_depth_limited_repo_stops_before_descendant_query_at_cap(db_with_user):
    db, user_id = db_with_user
    await _node(db, user_id, "root")
    await _node(db, user_id, "child")
    await edge_repo.add_edge(db, "root", "child")

    counted = _CountingDb(db)
    rows = await node_repo.get_node_tree_to_depth(
        counted,
        "root",
        max_depth=1000,
        max_nodes=1,
    )

    assert [row["node_id"] for row in rows] == ["root"]
    assert counted.execute_count == 1
    assert all("node_edges" not in sql for sql in counted.executed_sql)
