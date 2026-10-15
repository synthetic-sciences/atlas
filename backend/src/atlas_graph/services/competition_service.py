"""Competitions: public research challenges with graph-backed leaderboards.

A competition is a metric + constraint + deadline; an entry links a public
research graph to a submitter and a score. The leaderboard ranks entries by
score in the competition's goal direction (lower-is-better or higher-is-better).
All read paths are public; the module is additive over the existing schema.

Queries use ``?`` placeholders, which the connection layer translates for both
the aiosqlite (dev) and asyncpg (prod) backends.
"""
from __future__ import annotations

import json
from typing import Any


def _row(r) -> dict[str, Any]:
    return dict(r)


def _parse_credits(raw) -> list[dict]:
    """Credits attribute the original (often non-Atlas) authors by GitHub handle.
    Stored as a JSON array of handle strings or ``{handle, note}`` objects."""
    if not raw:
        return []
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return []
    out: list[dict] = []
    for item in data or []:
        if isinstance(item, str):
            out.append({"handle": item, "note": None})
        elif isinstance(item, dict) and item.get("handle"):
            out.append({"handle": item["handle"], "note": item.get("note")})
    return out


def _order(goal: str | None) -> str:
    # lower-is-better metrics (loss, bits/byte, latency) sort ascending
    return "ASC" if (goal or "min") == "min" else "DESC"


def _researcher(e: dict) -> dict:
    handle = e.get("github_username") or e.get("display_name") or "anonymous"
    return {
        "handle": handle,
        "github_username": e.get("github_username"),
        "display_name": e.get("display_name"),
        "avatar_url": e.get("avatar_url"),
    }


async def list_competition_cards(db, *, user_id: str | None = None) -> dict:
    """All competitions, ordered live → upcoming → ended, each with the entry
    count and current leader for a rich directory card."""
    cur = await db.execute(
        """
        SELECT * FROM competitions
        ORDER BY CASE status WHEN 'live' THEN 0 WHEN 'upcoming' THEN 1 ELSE 2 END,
                 ends_at ASC, created_at DESC
        """
    )
    comps = [_row(r) for r in await cur.fetchall()]
    cards = []
    for c in comps:
        cid = c["competition_id"]
        ec = await db.execute(
            "SELECT COUNT(*) AS n FROM competition_entries WHERE competition_id = ?",
            (cid,),
        )
        entry_count = int(_row(await ec.fetchone())["n"])
        lc = await db.execute(
            f"""
            SELECT e.score, u.github_username, u.display_name, u.avatar_url
            FROM competition_entries e
            LEFT JOIN users u ON u.user_id = e.user_id
            WHERE e.competition_id = ? AND e.score IS NOT NULL
            ORDER BY e.score {_order(c.get("metric_goal"))}
            LIMIT 1
            """,
            (cid,),
        )
        lrow = await lc.fetchone()
        leader = _researcher(_row(lrow)) if lrow else None
        leader_score = _row(lrow)["score"] if lrow else None
        cards.append(
            {
                **{k: c.get(k) for k in (
                    "competition_id", "slug", "title", "summary", "host_org",
                    "metric_label", "metric_goal", "metric_unit", "dataset",
                    "constraint_text", "prize", "repo_url", "paper_url",
                    "status", "starts_at", "ends_at",
                )},
                "entry_count": entry_count,
                "leader": leader,
                "leader_score": leader_score,
            }
        )
    return {"competitions": cards, "total": len(cards)}


async def get_competition_detail(db, slug: str, *, user_id: str | None = None) -> dict | None:
    """One competition plus its full ranked leaderboard (entry → graph + submitter)."""
    cur = await db.execute("SELECT * FROM competitions WHERE slug = ?", (slug,))
    row = await cur.fetchone()
    if not row:
        return None
    c = _row(row)
    ec = await db.execute(
        f"""
        SELECT e.entry_id, e.root_node_id, e.score, e.note, e.created_at,
               u.user_id, u.github_username, u.display_name, u.avatar_url,
               n.title AS graph_title, n.slug_name AS graph_slug
        FROM competition_entries e
        LEFT JOIN users u ON u.user_id = e.user_id
        LEFT JOIN nodes n ON n.node_id = e.root_node_id
        WHERE e.competition_id = ?
        ORDER BY (e.score IS NULL), e.score {_order(c.get("metric_goal"))}, e.created_at ASC
        """,
        (c["competition_id"],),
    )
    entries = [_row(r) for r in await ec.fetchall()]
    leaderboard = []
    for i, e in enumerate(entries):
        leaderboard.append(
            {
                "rank": i + 1,
                "entry_id": e["entry_id"],
                "score": e.get("score"),
                "note": e.get("note"),
                "submitted_at": e.get("created_at"),
                "graph": (
                    {
                        "node_id": e.get("root_node_id"),
                        "title": e.get("graph_title"),
                        "slug": e.get("graph_slug"),
                    }
                    if e.get("root_node_id")
                    else None
                ),
                "researcher": _researcher(e),
            }
        )
    return {
        **c,
        "credits": _parse_credits(c.get("credits")),
        "entry_count": len(entries),
        "leaderboard": leaderboard,
    }
