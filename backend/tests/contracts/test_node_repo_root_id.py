from __future__ import annotations

from uuid import uuid4

import pytest

from atlas_graph.db.repos import node_repo


class _FakeCursor:
    def __init__(self, row):
        self._row = row

    async def fetchone(self):
        return self._row


class _FakeDb:
    def __init__(self, row):
        self._row = row

    async def execute(self, sql, params):
        return _FakeCursor(self._row)


@pytest.mark.asyncio
async def test_find_root_node_id_stringifies_uuid_rows():
    root_id = uuid4()
    db = _FakeDb((root_id,))

    result = await node_repo.find_root_node_id(db, str(root_id))

    assert result == str(root_id)
