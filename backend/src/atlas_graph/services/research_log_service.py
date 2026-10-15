"""
Research log service - the append-only decision ledger.

Every interesting event gets a row in ``research_log`` + a line in
``<project>/research_log.jsonl``. The DB is the source of truth (queried
via ``get_research_log`` by the brain); the JSONL file is for human
forensics and lets ``tail -f`` work.

Entry types we currently emit:
- ``project_created``      - fresh project root node
- ``asset_registered``     - a volume file became an asset
- ``proposal_created``     - brain staged an experiment / proposed a canvas op
- ``node_committed``       - a node's lifecycle advanced to committed
- ``agent_spawned``        - a sub-agent lease acquired (Phase 4)
- ``agent_result``         - a sub-agent finished (Phase 4)
- ``dead_end``             - user marked a direction as not worth pursuing
- ``decision``             - free-form decision recorded by the brain
- ``assumption`` / ``result`` / ``failure`` / ``pivot`` - typed research notes
"""

from __future__ import annotations

from typing import Any

from atlas_graph import fs
from atlas_graph.db.repos import research_log_repo


async def append(
    db,
    *,
    project_id: str,
    entry_type: str,
    title: str,
    body: str | None = None,
    refs: list[dict[str, Any]] | None = None,
    created_by: str,
) -> dict[str, Any]:
    """Write an entry to the DB ledger + the project's JSONL mirror.

    ``created_by`` is either a user_id (for user-initiated entries), an
    agent_id (for sub-agent entries), or a string like "brain" for the
    chat agent.
    """
    entry = await research_log_repo.insert(
        db,
        project_id=project_id,
        entry_type=entry_type,
        title=title,
        body=body,
        refs=refs,
        created_by=created_by,
    )

    # Best-effort JSONL mirror. If the volume isn't reachable we still
    # succeed - the DB row is canonical.
    try:
        fs.ensure_project_volume(project_id)
        fs.append_research_log_line(project_id, entry)
    except Exception:
        pass

    return entry


async def list_entries(
    db,
    *,
    project_id: str,
    entry_types: list[str] | None = None,
    since: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    return await research_log_repo.list_entries(
        db,
        project_id=project_id,
        entry_types=entry_types,
        since=since,
        limit=limit,
    )


async def search(
    db,
    *,
    project_id: str,
    query: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    return await research_log_repo.search(
        db, project_id=project_id, query=query, limit=limit
    )


async def count(
    db, *, project_id: str, entry_type: str | None = None
) -> int:
    return await research_log_repo.count(
        db, project_id=project_id, entry_type=entry_type
    )


__all__ = ["append", "list_entries", "search", "count"]
