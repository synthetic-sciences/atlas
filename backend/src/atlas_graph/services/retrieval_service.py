"""
Graph-as-KB retrieval service (Knowledge v0, U5).

Two public entry points used by the rest of the knowledge layer:

* :func:`embed_node`  - chunk a committed node's text fields, embed each
  chunk via :mod:`app.clients.openai_embed`, and insert rows into
  ``knowledge_chunks``.  Called by ``indexer_worker``.
* :func:`search_graph` - given a query (string or pre-embedded vector),
  return the top-k chunks the caller's user_id is permitted to see.  ACL
  joins ``nodes`` + ``node_access_rules``.  Called by
  ``knowledge_router.unified_search``.

Postgres path uses pgvector's cosine-distance operator (``<=>``) against
the HNSW index in ``knowledge_chunks.embedding``.  The SQLite dev path
falls back to a LIKE/BM25 full-text search over ``chunk_text`` since
pgvector is not available; retrieval quality is lower but local dev
works without external deps.

A thin :func:`embed_text` wrapper re-exports the managed OpenRouter embedder
with a stable ``(vec, embedding_id)`` tuple that matches what the router
expects.  The ``embedding_id`` is always ``None`` in v0 (we don't store
query-embeddings for audit), but the shape leaves room for P1.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

from atlas_graph import config
from atlas_graph.clients import openai_embed
from atlas_graph.runtime import host

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

# Rough heuristic token count: the embedding model averages ~4 chars per token for
# English prose, so "tokens" here are approximated as ``len(text) // 4``.
# Keeps the implementation dependency-free (no tiktoken needed in v0).
_CHARS_PER_TOKEN = 4
_MAX_TOKENS_PER_CHUNK = 512
_OVERLAP_TOKENS = 50
_MAX_CHARS_PER_CHUNK = _MAX_TOKENS_PER_CHUNK * _CHARS_PER_TOKEN
_OVERLAP_CHARS = _OVERLAP_TOKENS * _CHARS_PER_TOKEN


def _split_with_overlap(text: str, max_chars: int, overlap: int) -> list[str]:
    """Hard-wrap ``text`` at ``max_chars``, preserving ``overlap`` chars between adjacent chunks."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    pieces: list[str] = []
    start = 0
    step = max_chars - overlap
    if step <= 0:
        step = max_chars
    while start < len(text):
        end = min(start + max_chars, len(text))
        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)
        if end >= len(text):
            break
        start += step
    return pieces


def _chunk_content(content: str) -> list[str]:
    """Split the ``content`` field into paragraph-ish chunks with 50-token overlap.

    Paragraphs (blank-line-delimited) are kept intact when they fit under
    the 512-token limit; longer paragraphs are hard-wrapped with overlap.
    Short consecutive paragraphs are packed into the same chunk up to the
    size limit.
    """
    if not content or not content.strip():
        return []

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", content) if p.strip()]

    chunks: list[str] = []
    buf: list[str] = []
    buf_len = 0
    for para in paragraphs:
        if len(para) > _MAX_CHARS_PER_CHUNK:
            # Flush the buffer first so order is preserved.
            if buf:
                chunks.append("\n\n".join(buf))
                buf, buf_len = [], 0
            chunks.extend(
                _split_with_overlap(para, _MAX_CHARS_PER_CHUNK, _OVERLAP_CHARS)
            )
            continue

        # +2 for the "\n\n" joiner between paragraphs.
        projected = buf_len + (2 if buf else 0) + len(para)
        if projected > _MAX_CHARS_PER_CHUNK and buf:
            chunks.append("\n\n".join(buf))
            buf, buf_len = [para], len(para)
        else:
            buf.append(para)
            buf_len = projected

    if buf:
        chunks.append("\n\n".join(buf))

    return chunks


def _node_chunks(node: dict[str, Any]) -> list[dict[str, Any]]:
    """Derive chunks + per-chunk metadata from a node row.

    Returns a list of ``{"text": str, "metadata": dict}`` in ordinal order.
    The caller is responsible for assigning ``ordinal`` indices.
    """
    out: list[dict[str, Any]] = []

    title = (node.get("title") or "").strip()
    summary = (node.get("summary") or "").strip()
    if title or summary:
        combined = "\n\n".join(x for x in (title, summary) if x)
        out.extend(
            {"text": text, "metadata": {"field": "title_summary"}}
            for text in _split_with_overlap(
                combined, _MAX_CHARS_PER_CHUNK, _OVERLAP_CHARS
            )
        )

    content = node.get("content") or ""
    for para_chunk in _chunk_content(content):
        out.append({"text": para_chunk, "metadata": {"field": "content"}})

    hypothesis = (node.get("hypothesis") or "").strip()
    if hypothesis:
        out.extend(
            {"text": text, "metadata": {"field": "hypothesis"}}
            for text in _split_with_overlap(
                hypothesis, _MAX_CHARS_PER_CHUNK, _OVERLAP_CHARS
            )
        )

    insights = node.get("insights")
    if isinstance(insights, str):
        try:
            insights = json.loads(insights)
        except (json.JSONDecodeError, TypeError):
            insights = []
    if isinstance(insights, list):
        for idx, insight in enumerate(insights):
            text = (insight or "").strip() if isinstance(insight, str) else ""
            if text:
                out.extend(
                    {"text": part, "metadata": {"field": "insight", "index": idx}}
                    for part in _split_with_overlap(
                        text, _MAX_CHARS_PER_CHUNK, _OVERLAP_CHARS
                    )
                )

    return out


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _is_postgres() -> bool:
    """Return True when the app is running against Postgres."""
    try:
        return bool(getattr(config, "USE_POSTGRES", False))
    except Exception:
        return False


async def _fetchone(db, sql: str, params: tuple) -> Any:
    cursor = await db.execute(sql, params)
    try:
        row = await cursor.fetchone()
    finally:
        close = getattr(cursor, "close", None)
        if close is not None:
            await close()
    return row


async def _fetchall(db, sql: str, params: tuple) -> list[Any]:
    cursor = await db.execute(sql, params)
    try:
        rows = await cursor.fetchall()
    finally:
        close = getattr(cursor, "close", None)
        if close is not None:
            await close()
    return rows


def _row_to_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    if row is None:
        return {}
    if hasattr(row, "keys"):
        return {k: row[k] for k in row.keys()}
    return {}


async def _node_source_id(db, node_id: str, owner_user_id: str) -> str:
    """Return (creating if necessary) the ``knowledge_sources.source_id`` for a node.

    Graph-backed chunks live in a synthetic source of type ``graph`` keyed
    off the node id.  Creating the row lets the foreign key from
    ``knowledge_chunks.source_id`` resolve without changing schema.
    """
    source_id = f"graph:{node_id}"
    now = datetime.now(timezone.utc).isoformat()

    # INSERT ... ON CONFLICT DO NOTHING works for both SQLite and Postgres.
    await db.execute(
        """INSERT INTO knowledge_sources
               (source_id, owner_user_id, source_type, display_name,
                external_ref, status, metadata, created_at, updated_at)
           VALUES (?, ?, 'graph', ?, ?, 'ready', '{}', ?, ?)
           ON CONFLICT (source_id) DO NOTHING""",
        (source_id, owner_user_id, f"node:{node_id}", node_id, now, now),
    )
    return source_id


# ---------------------------------------------------------------------------
# Public API: embedding
# ---------------------------------------------------------------------------


async def embed_text(
    text: str,
    *,
    db=None,
    user_id: str | None = None,
) -> tuple[list[float], str | None]:
    """Embed ``text`` via OpenRouter; return ``(vector, embedding_id)``.

    When ``db`` + ``user_id`` are provided, this call is metered: one
    ``llm_usage`` row is written and the user's credit balance is
    debited via ``usage_service``. Pass them whenever the embedding is
    on behalf of a specific request from a user (search queries, node
    indexing triggered by a user action).
    """
    vec = await openai_embed.embed_text(
        text,
        db=db,
        user_id=user_id,
        endpoint="graph_search_embedding",
    )
    return vec, None


@asynccontextmanager
async def _index_write(db):
    raw = getattr(db, "raw", None)
    if raw is not None:
        async with raw.transaction():
            yield
        return
    nested = db.in_transaction
    await db.execute("SAVEPOINT atlas_index_write" if nested else "BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        if nested:
            await db.execute("ROLLBACK TO atlas_index_write")
            await db.execute("RELEASE atlas_index_write")
        else:
            await db.rollback()
        raise
    else:
        if nested:
            await db.execute("RELEASE atlas_index_write")
        else:
            await db.commit()


async def embed_node(db, node_id: str, *, guard=None, complete=None) -> int:
    """Chunk a node's text fields, embed each chunk, and write knowledge_chunks rows.

    Returns the number of chunks written.  Previously-embedded chunks for
    the same node are deleted before re-insert, so the function is
    idempotent (safe to call on every ``stage_update``).
    """
    node_row = await _fetchone(
        db,
        "SELECT node_id, owner_user_id, revision, title, summary, content, hypothesis, insights "
        "FROM nodes WHERE node_id = ?",
        (node_id,),
    )
    if node_row is None:
        logger.warning("embed_node: node %s not found", node_id)
        return 0
    node = _row_to_dict(node_row)

    chunks = _node_chunks(node)
    if not chunks:
        logger.info("embed_node: node %s has no embeddable text", node_id)
        return 0

    # Bill the node owner - they triggered the (re)index indirectly by
    # staging or committing this node.
    callback = host().index
    vectors = (
        await callback(node, chunks)
        if callback is not None
        else await openai_embed.embed_batch(
            [c["text"] for c in chunks],
            db=db,
            user_id=node["owner_user_id"],
            endpoint="graph_index_embedding",
        )
    )
    if len(vectors) != len(chunks):  # pragma: no cover - defensive
        raise RuntimeError(
            f"embed_node: embedder returned {len(vectors)} vectors for {len(chunks)} chunks"
        )

    async with _index_write(db):
        current = await _fetchone(
            db,
            "SELECT node_id,owner_user_id,revision,title,summary,content,hypothesis,insights FROM nodes WHERE node_id=?"
            + (" FOR UPDATE" if getattr(db, "raw", None) is not None else ""),
            (node_id,),
        )
        current = _row_to_dict(current)
        if (
            not current
            or current["owner_user_id"] != node["owner_user_id"]
            or current["revision"] != node["revision"]
            or _node_chunks(current) != chunks
        ):
            return 0
        if guard is not None and not await guard(db):
            return 0
        # Create the graph source only after managed embedding has been accepted
        # and settled.  In SQLite, writing it before ``place_hold`` borrowed an
        # unrelated open transaction across the provider call and prevented the
        # hold helper from committing its own preauthorization boundary.
        source_id = await _node_source_id(db, node_id, node["owner_user_id"])

        # Wipe any previous embedding for this node so re-embedding is idempotent.
        await db.execute(
            "DELETE FROM knowledge_chunks WHERE node_id = ?",
            (node_id,),
        )

        is_pg = _is_postgres()
        for ordinal, (chunk, vec) in enumerate(zip(chunks, vectors)):
            chunk_id = str(uuid.uuid4())
            meta_json = json.dumps(chunk["metadata"])
            if is_pg:
                embedding_literal = _vector_literal(vec)
                await db.execute(
                    """INSERT INTO knowledge_chunks
                           (chunk_id, source_id, node_id, chunk_text,
                            embedding, ordinal, metadata)
                       VALUES (?, ?, ?, ?, ?::vector, ?, ?::jsonb)""",
                    (
                        chunk_id,
                        source_id,
                        node_id,
                        chunk["text"],
                        embedding_literal,
                        ordinal,
                        meta_json,
                    ),
                )
            else:
                # SQLite: store the vector as a JSON-encoded text blob.  We
                # don't run vector math here (FTS-only fallback) but preserving
                # the payload lets offline migration scripts re-ingest.
                await db.execute(
                    """INSERT INTO knowledge_chunks
                           (chunk_id, source_id, node_id, chunk_text,
                            embedding, ordinal, metadata)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        chunk_id,
                        source_id,
                        node_id,
                        chunk["text"],
                        json.dumps(vec),
                        ordinal,
                        meta_json,
                    ),
                )

        if complete is not None:
            await complete(db)
    logger.info("embed_node: wrote %d chunks for node %s", len(chunks), node_id)
    return len(chunks)


async def embed_nodes(
    db_or_node_ids,
    node_ids: Iterable[str] | None = None,
) -> int:
    """Embed several nodes, acquiring a DB connection for worker calls.

    Request-scoped callers may pass ``(db, node_ids)``.  The background
    indexer historically calls ``embed_nodes(node_ids)``; that form now opens
    a real pooled connection so node-owner attribution, Wallet holds, and the
    chunk writes all execute instead of failing on an argument mismatch.
    """
    if node_ids is None:
        from atlas_graph.db.connection import get_db

        queued_ids = list(db_or_node_ids)
        async with get_db() as db:
            return await embed_nodes(db, queued_ids)

    db = db_or_node_ids
    total = 0
    for nid in node_ids:
        total += await embed_node(db, nid)
    return total


def _vector_literal(vec: list[float]) -> str:
    """Format a float list as the ``[1.0,2.0,...]`` literal pgvector expects."""
    return "[" + ",".join(f"{float(x):.6f}" for x in vec) + "]"


# ---------------------------------------------------------------------------
# Public API: search
# ---------------------------------------------------------------------------


# Sharing modes that are visible to everyone.  The Postgres enum is
# ``private | public | unlisted`` - only list values that exist in the enum.
_PUBLIC_SHARING_MODES = ("public", "unlisted")


def _publicsm_sql(alias: str) -> str:
    if not config.PUBLIC_GRAPHS_ENABLED:
        return "1 = 0"
    quoted = ",".join(f"'{m}'" for m in _PUBLIC_SHARING_MODES)
    return f"{alias}.sharing_mode IN ({quoted})"


def _root_access_sql(node_id_sql: str) -> str:
    """Correlated graph-root ACL for a node/chunk, shared by both DB paths."""
    return f"""
        EXISTS (
          WITH RECURSIVE ancestors(current_id) AS (
            SELECT {node_id_sql}
            UNION
            SELECT e.parent_id
              FROM node_edges e
              JOIN ancestors a ON e.child_id = a.current_id
          )
          SELECT 1
            FROM ancestors a
            JOIN nodes r ON r.node_id = a.current_id
           WHERE NOT EXISTS (
                 SELECT 1 FROM node_edges parent_edge
                  WHERE parent_edge.child_id = r.node_id
           )
             AND ({_publicsm_sql("r")}
                  OR r.owner_user_id = ?
                  OR EXISTS (
                      SELECT 1 FROM node_access_rules root_access
                       WHERE root_access.node_id = r.node_id
                         AND root_access.user_id = ?
                  ))
        )
    """


async def _search_pg(
    db, user_id: str, query_vec: list[float], k: int
) -> list[dict[str, Any]]:
    vec_literal = _vector_literal(query_vec)
    sql = f"""
        SELECT kc.chunk_id, kc.source_id, kc.node_id, kc.chunk_text,
               kc.metadata, kc.ordinal,
               (kc.embedding <=> ?::vector) AS distance
        FROM knowledge_chunks kc
        JOIN nodes n ON n.node_id = kc.node_id
        WHERE ({_root_access_sql("kc.node_id")})
          AND kc.embedding IS NOT NULL
        ORDER BY kc.embedding <=> ?::vector
        LIMIT ?
    """
    rows = await _fetchall(db, sql, (vec_literal, user_id, user_id, vec_literal, k))
    return [_coerce_row(r) for r in rows]


async def _search_sqlite(
    db, user_id: str, query_text: str, k: int
) -> list[dict[str, Any]]:
    """Dev fallback: LIKE-scan ``chunk_text`` with the same ACL as the PG path.

    We tokenise the query on whitespace and score rows by the number of
    distinct tokens that appear (case-insensitive) in the chunk text.  It's
    intentionally simple - dev loops don't need FTS5 quality.
    """
    tokens = [t.strip().lower() for t in re.split(r"\s+", query_text) if t.strip()]
    if not tokens:
        return []

    like_clauses = " OR ".join(["lower(kc.chunk_text) LIKE ?"] * len(tokens))
    like_params = [f"%{t}%" for t in tokens]
    sql = f"""
        SELECT kc.chunk_id, kc.source_id, kc.node_id, kc.chunk_text,
               kc.metadata, kc.ordinal
        FROM knowledge_chunks kc
        JOIN nodes n ON n.node_id = kc.node_id
        WHERE ({_root_access_sql("kc.node_id")})
          AND ({like_clauses})
        LIMIT ?
    """
    params = tuple([user_id, user_id] + like_params + [k * 4])
    rows = await _fetchall(db, sql, params)

    hits: list[dict[str, Any]] = []
    for raw in rows:
        r = _coerce_row(raw)
        text_lower = (r.get("chunk_text") or "").lower()
        hit_count = sum(1 for t in tokens if t in text_lower)
        if not hit_count:
            continue
        # Map 0..len(tokens) into a pseudo-distance (smaller = better).
        r["distance"] = max(0.0, 1.0 - (hit_count / len(tokens)))
        hits.append(r)

    hits.sort(key=lambda r: r["distance"])
    return hits[:k]


def _coerce_row(raw: Any) -> dict[str, Any]:
    row = _row_to_dict(raw)
    meta = row.get("metadata")
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except (json.JSONDecodeError, TypeError):
            meta = {}
    elif meta is None:
        meta = {}
    return {
        "chunk_id": row.get("chunk_id"),
        "source_id": row.get("source_id"),
        "node_id": row.get("node_id"),
        "chunk_text": row.get("chunk_text") or "",
        "ordinal": row.get("ordinal"),
        "metadata": meta,
        "distance": row.get("distance"),
    }


async def search_graph(
    db,
    user_id: str,
    query: Any,
    *,
    k: int = 10,
    filters: dict | None = None,
) -> list[dict[str, Any]]:
    """Return up to ``k`` chunks permitted to ``user_id`` that match ``query``.

    Parameters
    ----------
    db
        Open DB connection (aiosqlite or the asyncpg wrapper).
    user_id : str
        The caller's user id - enforces ACL against ``node_access_rules``.
    query : list[float] | str
        Either a pre-computed embedding vector (Postgres path) or a plain
        string query.  When a string is passed to the Postgres path we
        call :func:`embed_text` to obtain the vector; the SQLite path
        always uses the string form.
    k : int
        Maximum number of results to return.
    filters : dict | None
        Reserved for P1 (source_type / date / tag filters).  Ignored in v0.

    Returns
    -------
    list[dict]
        Each dict has keys ``chunk_id, source_id, node_id, chunk_text,
        score, metadata, distance`` (``score`` is ``1 - distance`` for
        router compat; ``distance`` is preserved for callers that want
        raw cosine distance).
    """
    if k <= 0:
        return []

    is_pg = _is_postgres()
    if is_pg:
        if isinstance(query, str):
            vec, _ = await embed_text(query, db=db, user_id=user_id)
        else:
            vec = list(query) if query is not None else []
        if not vec:
            return []
        hits = await _search_pg(db, user_id, vec, k)
    else:
        # SQLite dev fallback: require the plain-text form.  If the caller
        # only has a vector we can't run vector math here, so we return
        # an empty list rather than silently mis-ranking results.
        if not isinstance(query, str):
            logger.debug(
                "search_graph: SQLite path requires a string query; caller passed %s",
                type(query).__name__,
            )
            return []
        hits = await _search_sqlite(db, user_id, query, k)

    for r in hits:
        dist = r.get("distance")
        try:
            r["score"] = 1.0 - float(dist) if dist is not None else 0.0
        except (TypeError, ValueError):
            r["score"] = 0.0
    return hits
