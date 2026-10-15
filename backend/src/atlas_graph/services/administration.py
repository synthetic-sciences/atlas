"""Graph-only operations for a separately authenticated hosting administrator."""

from datetime import datetime, timedelta, timezone

from atlas_graph.services import export_import_service


def _parse_admin_cursor(cursor: str | None) -> int:
    if cursor in (None, ""):
        return 0
    try:
        offset = int(str(cursor))
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid cursor") from exc
    if offset < 0:
        raise ValueError("Invalid cursor")
    return offset


async def roots(
    db,
    *,
    tag_id: str | None,
    kind: str | None,
    owner_user_id: str | None,
    created_after: str | None,
    created_before: str | None,
    cursor: str | None,
    page_size: int,
) -> dict:
    clauses = ["NOT EXISTS (SELECT 1 FROM node_edges e WHERE e.child_id = n.node_id)"]
    params: list = []
    if tag_id:
        clauses.append(
            "EXISTS (SELECT 1 FROM tag_assignments ta WHERE ta.node_id = n.node_id AND ta.tag_id = ?)"
        )
        params.append(tag_id)
    if kind:
        clauses.append("n.node_type = ?")
        params.append(kind)
    if owner_user_id:
        clauses.append("n.owner_user_id = ?")
        params.append(owner_user_id)
    if created_after:
        clauses.append("n.created_at >= ?")
        params.append(created_after)
    if created_before:
        clauses.append("n.created_at < ?")
        params.append(created_before)
    where = " AND ".join(clauses)
    count_cursor = await db.execute(
        f"SELECT COUNT(*) FROM nodes n WHERE {where}",
        params,
    )
    total_count = (await count_cursor.fetchone())[0]
    offset = _parse_admin_cursor(cursor)
    rows_cursor = await db.execute(
        f"""
        SELECT n.node_id, n.slug_name, n.title, n.node_type AS kind,
               n.lifecycle, n.owner_user_id, n.created_at, n.updated_at,
               n.revision
        FROM nodes n
        WHERE {where}
        ORDER BY n.created_at DESC
        LIMIT ? OFFSET ?
        """,
        params + [page_size, offset],
    )
    columns = [desc[0] for desc in rows_cursor.description]
    graphs = [dict(zip(columns, row)) for row in await rows_cursor.fetchall()]
    end = offset + len(graphs)
    return {
        "graphs": graphs,
        "items": graphs,
        "count": len(graphs),
        "total_count": total_count,
        "page_info": {
            "start_cursor": str(offset) if total_count else None,
            "end_cursor": str(end) if end < total_count else None,
            "has_next_page": end < total_count,
            "has_previous_page": offset > 0,
        },
    }


async def summary(db, *, since: datetime) -> dict:
    cutoff = since.isoformat()
    totals = await (
        await db.execute(
            "SELECT COUNT(*) AS total_projects,COALESCE(SUM(CASE WHEN n.updated_at>=? THEN 1 ELSE 0 END),0) AS active_projects "
            "FROM nodes n WHERE NOT EXISTS (SELECT 1 FROM node_edges e WHERE e.child_id=n.node_id)",
            (cutoff,),
        )
    ).fetchone()
    nodes = await (await db.execute("SELECT COUNT(*) FROM nodes")).fetchone()
    daily = {}
    for column in ("created_at", "updated_at"):
        cursor = await db.execute(
            f"SELECT DATE(n.{column}) AS date,COUNT(*) AS projects FROM nodes n WHERE n.{column}>=? "
            "AND NOT EXISTS (SELECT 1 FROM node_edges e WHERE e.child_id=n.node_id) "
            f"GROUP BY DATE(n.{column}) ORDER BY DATE(n.{column})",
            (cutoff,),
        )
        daily[column] = [
            {"date": str(row[0]), "projects": int(row[1])}
            for row in await cursor.fetchall()
        ]
    return {
        "total_projects": int(totals[0]),
        "active_projects": int(totals[1]),
        "total_nodes": int(nodes[0]),
        **daily,
    }


async def owners(db, user_ids: list[str]) -> dict[str, int]:
    if not user_ids:
        return {}
    marks = ",".join("?" for _ in user_ids)
    cursor = await db.execute(
        f"SELECT n.owner_user_id,COUNT(*) FROM nodes n WHERE n.owner_user_id IN ({marks}) "
        "AND NOT EXISTS (SELECT 1 FROM node_edges e WHERE e.child_id=n.node_id) GROUP BY n.owner_user_id",
        tuple(user_ids),
    )
    return {str(row[0]): int(row[1]) for row in await cursor.fetchall()}


async def purge(db, *, days: int, dry_run: bool) -> dict:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    row = await (
        await db.execute(
            "SELECT COUNT(*) FROM audit_events WHERE timestamp<?", (cutoff,)
        )
    ).fetchone()
    count = int(row[0])
    if not dry_run:
        await db.execute("DELETE FROM audit_events WHERE timestamp<?", (cutoff,))
        await db.commit()
    return {
        "dry_run": dry_run,
        "cutoff": cutoff,
        "would_delete" if dry_run else "deleted": count,
    }


async def export(db, *, actor: str, node_id: str, max_nodes: int | None) -> dict:
    graph = await export_import_service.export_subgraph(
        db,
        actor,
        [node_id],
        include_descendants=True,
        max_nodes=max_nodes,
        skip_access_check=True,
    )
    return {"root_node_id": node_id, "export": graph}
