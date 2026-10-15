"""Native graph-backed knowledge search.

The retired external Library branch is deliberately absent. This module only
embeds the query, searches caller-accessible graph chunks, and preserves the
compact compatibility response consumed by older clients.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Literal

logger = logging.getLogger(__name__)

def _is_embedding_billing_error(exc: Exception) -> bool:
    """Return whether graph search must surface rather than degrade around it."""
    from atlas_graph.clients.openai_embed import EmbeddingBillingError
    from atlas_graph.runtime import host

    provider = host().billing_errors
    errors = provider() if provider is not None else ()

    return isinstance(
        exc,
        (EmbeddingBillingError, *errors),
    )


def _get_retrieval_service():
    """Import and return ``app.services.retrieval_service`` (or None)."""
    try:
        from atlas_graph.services import retrieval_service  # noqa: WPS433 (runtime import)
        return retrieval_service
    except Exception as exc:  # pragma: no cover - sibling module absent
        logger.debug("retrieval_service unavailable: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def _coerce_result(
    raw: Any,
    *,
    default_source_type: str,
) -> dict[str, Any] | None:
    """Coerce a branch result (dict-like) into the router's canonical shape.

    Returns None for results that cannot be usefully represented (no text, no
    score).  Always preserves ``metadata`` if present.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        # Some clients may return small dataclasses; attempt a best-effort
        # conversion.
        try:
            raw = dict(raw)
        except Exception:
            return None

    text = raw.get("text") or raw.get("chunk_text") or ""
    score = raw.get("score")
    # Graph results often carry cosine ``distance`` rather than ``score``.
    if score is None and "distance" in raw:
        try:
            score = 1.0 - float(raw["distance"])
        except (TypeError, ValueError):
            score = None
    if score is None:
        score = 0.0

    return {
        "chunk_id": raw.get("chunk_id"),
        "source_id": raw.get("source_id"),
        "source_type": raw.get("source_type") or default_source_type,
        "text": text,
        "score": float(score),
        "metadata": raw.get("metadata") or {},
        "node_id": raw.get("node_id"),
        "external_ref": raw.get("external_ref"),
    }


def _normalize_scores(results: list[dict[str, Any]]) -> None:
    """In-place min-max normalize the ``score`` field to [0,1]."""
    if not results:
        return
    scores = [r["score"] for r in results]
    lo = min(scores)
    hi = max(scores)
    if hi <= lo:
        for r in results:
            r["score"] = 1.0 if hi > 0 else 0.0
        return
    span = hi - lo
    for r in results:
        r["score"] = (r["score"] - lo) / span


def _dedupe(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop lower-scored duplicates that share text or external_ref."""
    seen_text: dict[str, dict[str, Any]] = {}
    seen_ref: dict[str, dict[str, Any]] = {}
    out: list[dict[str, Any]] = []
    for r in results:
        text_key = (r.get("text") or "").strip()
        ref_key = r.get("external_ref")

        dup_by_text = seen_text.get(text_key) if text_key else None
        dup_by_ref = seen_ref.get(ref_key) if ref_key else None
        dup = dup_by_text or dup_by_ref
        if dup is not None:
            # Keep the higher-scored one.
            if r["score"] > dup["score"]:
                # Replace in output list + index.
                try:
                    out[out.index(dup)] = r
                except ValueError:
                    out.append(r)
                if text_key:
                    seen_text[text_key] = r
                if ref_key:
                    seen_ref[ref_key] = r
            # else: drop r.
            continue
        out.append(r)
        if text_key:
            seen_text[text_key] = r
        if ref_key:
            seen_ref[ref_key] = r
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def unified_search(
    db,
    user_id: str,
    query: str,
    *,
    k: int = 10,
    mode: Literal["targeted", "universal", "web"] = "targeted",
    filters: dict | None = None,
    source_ids: list[str] | None = None,
    include_graph: bool = True,
    include_external: bool = True,
) -> dict[str, Any]:
    """Search native graph chunks and return the compatibility result shape.

    Returns a dict of the form:
        {
            "results": list[dict],   # up to k items, each with score/text/...
            "total":   int,          # len(results)
            "query_embedding_id": str | None,
            "latency_ms": int,
        }
    """
    t0 = time.monotonic()

    run_graph = include_graph

    # ---- Embed query (only needed for graph branch) ----------------------
    # Keep this inside the graph coroutine so an unavailable embedding provider
    # preserves the existing bounded graph-only degradation behavior.
    query_embedding_id: str | None = None
    retrieval_service = _get_retrieval_service()

    # ---- Search the native graph -----------------------------------------

    async def _graph_branch() -> list[dict[str, Any]]:
        nonlocal query_embedding_id
        if not run_graph or retrieval_service is None:
            return []
        query_vec: list[float] | None = None
        try:
            embed_result = await retrieval_service.embed_text(
                query, db=db, user_id=user_id,
            )
            if isinstance(embed_result, tuple):
                query_vec, query_embedding_id = embed_result
            elif isinstance(embed_result, dict):
                query_vec = embed_result.get("embedding") or embed_result.get(
                    "vector"
                )
                query_embedding_id = embed_result.get("embedding_id")
            else:
                query_vec = embed_result  # bare list[float]
        except Exception as exc:
            if _is_embedding_billing_error(exc):
                raise
            logger.warning("unified_search: embed_text failed: %s", exc)
            query_vec = None
        try:
            raw = await retrieval_service.search_graph(
                db,
                user_id,
                query_vec,
                k=k * 2,
                filters=filters,
            )
        except Exception as exc:
            if _is_embedding_billing_error(exc):
                raise
            logger.warning("unified_search: graph branch failed: %s", exc)
            return []
        out: list[dict[str, Any]] = []
        for r in raw or []:
            c = _coerce_result(r, default_source_type="graph")
            if c is not None:
                out.append(c)
        return out

    graph_results = await _graph_branch()
    external_results: list[dict[str, Any]] = []

    # ---- Normalize graph scores ------------------------------------------
    _normalize_scores(graph_results)

    combined = graph_results + external_results
    combined.sort(key=lambda r: r["score"], reverse=True)

    # ---- Dedup then truncate ---------------------------------------------
    deduped = _dedupe(combined)
    truncated = deduped[:k]

    latency_ms = int((time.monotonic() - t0) * 1000)
    logger.info(
        "unified_search: user=%s graph=%d external=%d merged=%d "
        "returned=%d latency_ms=%d",
        user_id,
        len(graph_results),
        len(external_results),
        len(deduped),
        len(truncated),
        latency_ms,
    )

    return {
        "results": truncated,
        "graph_hits": graph_results[:k],
        "external_hits": external_results[:k],
        "total": len(truncated),
        "query_embedding_id": query_embedding_id,
        "latency_ms": latency_ms,
    }
