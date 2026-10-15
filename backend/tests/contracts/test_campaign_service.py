from __future__ import annotations

import pytest

from atlas_graph.services import campaign_service


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    async def fetchall(self):
        return self._rows


class _FakeDb:
    def __init__(self):
        self.queries: list[str] = []

    async def execute(self, sql, params):
        self.queries.append(sql)
        node_id = params[0]
        if "WHERE node_id = ? AND artifact_type = 'json'" in sql and node_id == "root-1":
            return _FakeCursor(
                [
                    {
                        "artifact_id": "cfg-1",
                        "artifact_type": "json",
                        "payload": '{"version":"campaign_config_v1","metric_key":"score"}',
                        "metadata": '{"campaign_role":"config"}',
                    }
                ]
            )
        if "WHERE node_id = ? AND artifact_type = 'json'" in sql and node_id == "child-1":
            return _FakeCursor(
                [
                    {
                        "artifact_id": "sub-1",
                        "artifact_type": "json",
                        "payload": "{}",
                        "metadata": '{"campaign_role":"submission"}',
                    }
                ]
            )
        return _FakeCursor([])


@pytest.mark.asyncio
async def test_get_snapshot_reads_campaign_config_from_json_artifact(monkeypatch):
    db = _FakeDb()

    async def _allow(*args, **kwargs):
        return None

    async def _find_root_node_id(*args, **kwargs):
        return "root-1"

    async def _get_node(*args, **kwargs):
        return {"node_id": "root-1", "title": "Root"}

    async def _get_node_tree(*args, **kwargs):
        return [
            {"node_id": "root-1", "node_type": "untyped", "lifecycle": "staged", "outcome": None},
            {
                "node_id": "child-1",
                "node_type": "empirical",
                "lifecycle": "committed",
                "outcome": "completed",
                "title": "Submission",
                "owner_user_id": "user-1",
            },
        ]

    async def _list_budgets(*args, **kwargs):
        return [{"budget_id": "budget-1"}]

    monkeypatch.setattr(campaign_service, "require_node_access", _allow)
    monkeypatch.setattr(campaign_service.node_repo, "find_root_node_id", _find_root_node_id)
    monkeypatch.setattr(campaign_service.node_repo, "get_node", _get_node)
    monkeypatch.setattr(campaign_service.node_repo, "get_node_tree", _get_node_tree)
    monkeypatch.setattr(campaign_service.campaign_repo, "list_budgets", _list_budgets)

    snapshot = await campaign_service.get_snapshot(db, "user-1", "root-1")

    assert snapshot["config_status"] == "configured"
    assert snapshot["submission_count"] == 1
    assert snapshot["budgets"] == [{"budget_id": "budget-1"}]
    assert all("artifact_type = 'campaign_config_v1'" not in sql for sql in db.queries)
