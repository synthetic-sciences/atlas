"""In-process serialized-bytes cache for hot public READ endpoints.

The public read surface (the Explore archive, graph trees, social counts,
artifact lists) is the launch's hottest traffic and, for anonymous callers, is
*identical across callers* and changes rarely. Caching the SERIALIZED, COMPRESSED
bytes lets a cache hit skip the DB round-trips, JSON encoding, AND gzip
compression, which compounds for scale:

  * it frees the capacity-bounded DB pool (12 conns) for writes and cold paths —
    cached reads touch the DB zero times, so read throughput stops competing for
    connections;
  * it cuts per-request event-loop work to "copy bytes -> socket"; and
  * it serves gzip-compressed bytes (the graph tree is ~305KB raw -> ~30KB
    gzipped), so the single worker pushes ~10x fewer bytes per request — raising
    the throughput ceiling — and the client downloads + parses ~10x less.

Bytes are produced by FastAPI's own ``JSONResponse`` so they are byte-identical
to the uncached path. Compression is negotiated against the caller's
``Accept-Encoding`` (with ``Vary: Accept-Encoding`` so shared caches stay
correct); the rare non-gzip client gets the decompressed bytes. A short TTL
bounds staleness; an LRU-by-age cap bounds memory. Only anonymous,
viewer-independent responses should be cached here — never per-viewer data.
"""

from __future__ import annotations

import gzip
import time
from typing import Any

from fastapi import Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

_DEFAULT_MAX_ENTRIES = 512
# Below this size gzip's framing overhead outweighs the savings; store raw.
_GZIP_MIN_BYTES = 860


def accepts_gzip(request: Request) -> bool:
    return "gzip" in request.headers.get("accept-encoding", "").lower()


class BytesResponseCache:
    """TTL + age-eviction cache returning ready-to-send, gzip-aware ``Response``s.

    Stores one payload per key: gzipped when it clears ``_GZIP_MIN_BYTES``, else
    raw. Not shared across machines (in-process) — correct for content that is
    cheap to recompute and tolerates a few seconds of cross-machine skew; the
    short TTL keeps every replica within ``ttl`` of the source of truth.
    """

    def __init__(self, ttl: float, max_entries: int = _DEFAULT_MAX_ENTRIES) -> None:
        self.ttl = ttl
        self.max_entries = max_entries
        # key -> (stored_at, payload, is_gzipped)
        self._store: dict[str, tuple[float, bytes, bool]] = {}

    def _response(self, payload: bytes, is_gzipped: bool, want_gzip: bool, cache_state: str) -> Response:
        headers = {
            "Cache-Control": f"public, max-age={int(self.ttl)}",
            "Vary": "Accept-Encoding",
            "X-Cache": cache_state,
        }
        if is_gzipped and want_gzip:
            headers["Content-Encoding"] = "gzip"
            return Response(content=payload, media_type="application/json", headers=headers)
        if is_gzipped:  # rare: caller can't take gzip -> decompress
            payload = gzip.decompress(payload)
        return Response(content=payload, media_type="application/json", headers=headers)

    def get(self, key: str, want_gzip: bool = True) -> Response | None:
        hit = self._store.get(key)
        if hit is not None and (time.monotonic() - hit[0]) < self.ttl:
            return self._response(hit[1], hit[2], want_gzip, "HIT")
        return None

    def put(self, key: str, data: Any, want_gzip: bool = True) -> Response:
        raw = JSONResponse(content=jsonable_encoder(data)).body
        if len(raw) >= _GZIP_MIN_BYTES:
            payload, is_gzipped = gzip.compress(raw, compresslevel=6), True
        else:
            payload, is_gzipped = raw, False
        store = self._store
        if len(store) >= self.max_entries and key not in store:
            oldest = min(store.items(), key=lambda kv: kv[1][0])[0]
            store.pop(oldest, None)
        store[key] = (time.monotonic(), payload, is_gzipped)
        return self._response(payload, is_gzipped, want_gzip, "MISS")

    def clear(self) -> None:
        self._store.clear()


__all__ = ["BytesResponseCache", "accepts_gzip"]
