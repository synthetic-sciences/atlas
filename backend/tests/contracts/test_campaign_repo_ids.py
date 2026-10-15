from __future__ import annotations

from uuid import uuid4

import pytest

from atlas_graph.db.repos import campaign_repo


class _FakeCursor:
    def __init__(self, rows=None):
        self._rows = rows or []
        self.rowcount = 1

    async def fetchone(self):
        return self._rows[0] if self._rows else None

    async def fetchall(self):
        return self._rows


class _FakeDb:
    def __init__(self):
        self.calls: list[tuple[str, tuple]] = []

    async def execute(self, sql, params):
        self.calls.append((sql, tuple(params)))
        return _FakeCursor()

    async def commit(self):
        return None


@pytest.mark.asyncio
async def test_campaign_repo_stringifies_uuid_identifiers():
    db = _FakeDb()
    budget_id = uuid4()
    root_node_id = uuid4()
    organizer_user_id = uuid4()

    await campaign_repo.create_budget(
        db,
        budget_id=budget_id,
        root_node_id=root_node_id,
        organizer_user_id=organizer_user_id,
        hard_cap_cents=100,
    )
    await campaign_repo.list_budgets(db, root_node_id)
    await campaign_repo.get_budget(db, budget_id)
    await campaign_repo.update_budget(db, budget_id, status="revoked")

    bound_params = [params for _, params in db.calls]
    assert str(budget_id) in bound_params[0]
    assert str(root_node_id) in bound_params[0]
    assert str(organizer_user_id) in bound_params[0]
    assert bound_params[1] == (str(root_node_id),)
    assert bound_params[2] == (str(budget_id),)
    assert bound_params[3][-1] == str(budget_id)
