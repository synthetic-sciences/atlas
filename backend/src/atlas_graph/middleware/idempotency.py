"""
Idempotency middleware for FastAPI.

Intercepts POST / PUT / DELETE requests that carry an ``Idempotency-Key``
header.  Behaviour:

1. Resolve the caller from the ``Authorization`` header (API key or
   Supabase JWT). Requests without a valid principal never read or write
   the table: the route returns its own 401 (or succeeds for legitimately
   public mutation routes such as login/register/webhooks).
2. The stored key is ``sha256(user_id:METHOD:path:Idempotency-Key)``, so a
   key is scoped to one principal *and* one request target. Another user,
   an anonymous caller, or the same user on a different path can never
   replay (or 409 against) someone else's record.
3. If the scoped key already exists *and* the ``request_hash`` matches →
   replay the stored response (status + body).
4. If the scoped key exists but the ``request_hash`` differs → ``409``.
5. If the key is new → let the request through, capture the response, and
   persist it with a 7-day TTL (``config.IDEMPOTENCY_TTL_DAYS``) - but only
   when the outcome is deterministic (2xx, 409, 422). 401/403/429/5xx are
   never stored, so a client that correctly reuses its key on retry can
   still succeed once the transient condition clears.

Requests without the header, and safe methods (GET, HEAD, OPTIONS), are
passed through unchanged.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime, timedelta

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from atlas_graph import config
from atlas_graph.db.connection import get_db

logger = logging.getLogger(__name__)

_MUTATION_METHODS = {"POST", "PUT", "DELETE", "PATCH"}

# Only outcomes that are a deterministic function of the request are worth
# replaying. 401/403 reflect mutable auth state, 408/429 and 5xx are
# transient - storing any of those would pin the client's retry to the
# failure for IDEMPOTENCY_TTL_DAYS.
_STORABLE_NON_2XX_STATUSES = frozenset({409, 422})

# These endpoints are intrinsically idempotent but their response reflects
# mutable authorization. Replaying a stored approved response after revocation
# would violate the access boundary (and could replay the private artifact URL).
_AUTHORIZATION_SENSITIVE_PATHS = frozenset({"/api/ascent/access/request"})
_AUTHORIZATION_SENSITIVE_PREFIXES = ("/api/admin/ascent/",)

# These routes authorize or report spend from a server-resolved Personal or
# organization Wallet. Generic replay happens before route dependencies, so it
# cannot prove that a credential is still valid or attach an authoritative
# funding-context response header. Funded routes therefore authenticate every
# request; research search retains its own durable, organization-scoped replay
# after funding resolution.
_FUNDING_SENSITIVE_PATHS = frozenset(
    {"/api/cli/usage", "/api/v1/ace", "/api/v1/research/search", "/api/knowledge/search"}
)
_FUNDING_SENSITIVE_PREFIXES = ("/api/llm/proxy/",)


def _too_large_response(message: str) -> Response:
    return Response(
        content=f'{{"detail":"{message}"}}',
        status_code=413,
        media_type="application/json",
    )


def _parse_content_length(raw: str | None) -> int | None:
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _should_store_status(status_code: int) -> bool:
    return 200 <= status_code < 300 or status_code in _STORABLE_NON_2XX_STATUSES


def _bearer_token(request: Request) -> str | None:
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return None
    parts = auth_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


async def _resolve_principal(request: Request) -> str | None:
    from fastapi import HTTPException
    from atlas_graph.dependencies import get_current_user

    try:
        user = await get_current_user(request)
    except HTTPException:
        return None
    return str(user["user_id"])


def _storage_key(user_id: str, method: str, path: str, idem_key: str) -> str:
    return hashlib.sha256(
        f"{user_id}:{method}:{path}:{idem_key}".encode("utf-8")
    ).hexdigest()


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """Starlette / FastAPI middleware that enforces idempotency semantics."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Only apply to mutation methods
        if request.method not in _MUTATION_METHODS:
            return await call_next(request)
        if request.method == "PUT" and request.url.path.startswith(
            ("/api/v1/artifacts/uploads/", "/api/artifacts/upload/")
        ):
            return await call_next(request)
        if request.url.path in _AUTHORIZATION_SENSITIVE_PATHS or request.url.path.startswith(
            _AUTHORIZATION_SENSITIVE_PREFIXES
        ):
            return await call_next(request)
        if request.url.path in _FUNDING_SENSITIVE_PATHS or request.url.path.startswith(
            _FUNDING_SENSITIVE_PREFIXES
        ):
            return await call_next(request)

        idem_key = request.headers.get("Idempotency-Key")
        if not idem_key:
            return await call_next(request)

        # Scope the record to the authenticated principal. Without one we
        # neither replay nor store: the route returns its own 401, and
        # public mutation routes behave exactly as they do without a key.
        user_id = await _resolve_principal(request)
        if not user_id:
            return await call_next(request)
        storage_key = _storage_key(user_id, request.method, request.url.path, idem_key)

        content_length = _parse_content_length(request.headers.get("Content-Length"))
        if content_length and content_length > config.IDEMPOTENCY_MAX_BODY_BYTES:
            return _too_large_response("Idempotent request body is too large")

        # Read the body and compute its hash.  We cache the body on the
        # request state so downstream handlers can still read it.
        body_bytes = await request.body()
        if len(body_bytes) > config.IDEMPOTENCY_MAX_BODY_BYTES:
            return _too_large_response("Idempotent request body is too large")
        request_hash = hashlib.sha256(body_bytes).hexdigest()

        async with get_db() as db:
            rows = await db.execute_fetchall(
                "SELECT request_hash, response_body, status_code, expires_at "
                "FROM idempotency_keys WHERE idempotency_key = ?",
                (storage_key,),
            )

            if rows:
                existing = rows[0]
                now_iso = datetime.now(UTC).isoformat()

                # Expired entries are treated as non-existent
                if existing["expires_at"] and existing["expires_at"] > now_iso:
                    if existing["request_hash"] != request_hash:
                        return Response(
                            content='{"detail":"Idempotency-Key reused with different request body"}',
                            status_code=409,
                            media_type="application/json",
                        )

                    # Replay the stored response
                    return Response(
                        content=existing["response_body"],
                        status_code=existing["status_code"],
                        media_type="application/json",
                    )

        # Key doesn't exist (or was expired) - process the request normally
        response = await call_next(request)

        content_type = response.headers.get("content-type", "")
        response_len = _parse_content_length(response.headers.get("content-length"))
        if "application/json" not in content_type:
            return response
        if response_len is None:
            return response
        if response_len > config.IDEMPOTENCY_MAX_RESPONSE_BYTES:
            return response

        # Read the full response body so we can store it
        response_body_parts: list[bytes] = []
        async for chunk in response.body_iterator:  # type: ignore[union-attr]
            if isinstance(chunk, str):
                response_body_parts.append(chunk.encode("utf-8"))
            else:
                response_body_parts.append(chunk)
        response_body = b"".join(response_body_parts)

        should_store = (
            len(response_body) <= config.IDEMPOTENCY_MAX_RESPONSE_BYTES
            and _should_store_status(response.status_code)
        )

        now = datetime.now(UTC)
        expires_at = now + timedelta(days=config.IDEMPOTENCY_TTL_DAYS)

        if should_store:
            async with get_db() as db:
                await db.execute(
                    "INSERT OR REPLACE INTO idempotency_keys "
                    "(idempotency_key, request_hash, response_body, status_code, "
                    " created_at, expires_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        storage_key,
                        request_hash,
                        response_body.decode("utf-8", errors="replace"),
                        response.status_code,
                        now.isoformat(),
                        expires_at.isoformat(),
                    ),
                )
                await db.commit()

        # Return a new Response with the same body/status/headers
        return Response(
            content=response_body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )
