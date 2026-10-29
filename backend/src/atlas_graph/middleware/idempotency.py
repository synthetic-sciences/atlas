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
5. Atomically claim new keys before dispatch; concurrent calls cannot run the
   mutation again. Capture deterministic responses (2xx, 409, 422) with a
   7-day TTL (``config.IDEMPOTENCY_TTL_DAYS``). Authorization/throttling
   rejections release the claim. Interrupted and 5xx outcomes retain it
   because the mutation may already have committed.

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
# replaying. Authorization/throttling rejections can release the claim;
# ambiguous failures keep it to prevent a second mutation.
_STORABLE_NON_2XX_STATUSES = frozenset({409, 422})

# These endpoints are intrinsically idempotent but their response reflects
# mutable authorization. Replaying a stored approved response after revocation
# would violate the access boundary (and could replay the private artifact URL).
_AUTHORIZATION_SENSITIVE_PATHS = frozenset({"/api/ascent/access/request"})
_AUTHORIZATION_SENSITIVE_PREFIXES = ("/api/admin/ascent/", "/api/internal/", "/api/sharing/")

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

        # Sharing always checks the current graph ACL and keeps account emails
        # transient; replacement of its complete policy is already idempotent.
        if "/access-policy" in request.url.path:
            return await call_next(request)

        if request.url.path.startswith(("/api/export/", "/api/v1/export")):
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

        maximum_body = config.IDEMPOTENCY_MAX_BODY_BYTES
        if request.url.path in {"/api/import/subgraph", "/api/v1/import"}:
            from atlas_graph.services.export_import_service import MAX_ARCHIVE_REQUEST_BYTES

            maximum_body = MAX_ARCHIVE_REQUEST_BYTES
        content_length = _parse_content_length(request.headers.get("Content-Length"))
        if content_length and content_length > maximum_body:
            return _too_large_response("Idempotent request body is too large")

        # Read the body and compute its hash.  We cache the body on the
        # request state so downstream handlers can still read it.
        body_bytes = await request.body()
        if len(body_bytes) > maximum_body:
            return _too_large_response("Idempotent request body is too large")
        request_hash = hashlib.sha256(body_bytes).hexdigest()

        now = datetime.now(UTC)
        expires_at = now + timedelta(days=config.IDEMPOTENCY_TTL_DAYS)
        async with get_db() as db:
            claimed = await db.execute(
                "INSERT INTO idempotency_keys "
                "(idempotency_key, request_hash, response_body, status_code, created_at, expires_at) "
                "VALUES (?, ?, NULL, NULL, ?, ?) "
                "ON CONFLICT (idempotency_key) DO UPDATE SET "
                "request_hash = excluded.request_hash, response_body = NULL, status_code = NULL, "
                "created_at = excluded.created_at, expires_at = excluded.expires_at "
                "WHERE idempotency_keys.expires_at <= ? AND idempotency_keys.status_code IS NOT NULL",
                (storage_key, request_hash, now.isoformat(), expires_at.isoformat(), now.isoformat()),
            )
            await db.commit()
            if claimed.rowcount == 0:
                rows = await db.execute_fetchall(
                    "SELECT request_hash, response_body, status_code FROM idempotency_keys "
                    "WHERE idempotency_key = ?",
                    (storage_key,),
                )
                if not rows:
                    return Response(
                        content='{"detail":"Idempotency-Key is being released; retry the same request"}',
                        status_code=409, media_type="application/json", headers={"Retry-After": "1"},
                    )
                existing = rows[0]
                if existing["request_hash"] != request_hash:
                    return Response(
                        content='{"detail":"Idempotency-Key reused with different request body"}',
                        status_code=409, media_type="application/json",
                    )
                if existing["status_code"] is None:
                    # An interrupted request may already have committed its
                    # effect. Never expire an unfinished claim into a retry.
                    return Response(
                        content='{"detail":"Idempotency-Key is in progress or its outcome is unknown"}',
                        status_code=409, media_type="application/json", headers={"Retry-After": "1"},
                    )
                return Response(
                    content=existing["response_body"], status_code=existing["status_code"],
                    media_type="application/json",
                )

        # The durable claim survives cancellation and an ambiguous server error.
        response = await call_next(request)

        # Authorization and throttling rejections occur before graph work and
        # can be retried after the caller's state changes. Keep ambiguous 5xx
        # outcomes claimed because graph helpers may already have committed.
        if response.status_code in {401, 403, 404, 405, 408, 429}:
            async with get_db() as db:
                await db.execute(
                    "DELETE FROM idempotency_keys WHERE idempotency_key = ? AND status_code IS NULL",
                    (storage_key,),
                )
                await db.commit()
            return response
        if not _should_store_status(response.status_code):
            return response

        content_type = response.headers.get("content-type", "")
        response_len = _parse_content_length(response.headers.get("content-length"))
        if "application/json" not in content_type or response_len is None or response_len > config.IDEMPOTENCY_MAX_RESPONSE_BYTES:
            # We cannot replay this body, but a successful mutation must not be
            # dispatched again merely because its response is large or binary.
            async with get_db() as db:
                await db.execute(
                    "UPDATE idempotency_keys SET response_body = ?, status_code = 409 "
                    "WHERE idempotency_key = ? AND status_code IS NULL",
                    ('{"detail":"Request completed but its response cannot be replayed; read the resulting resource"}', storage_key),
                )
                await db.commit()
            return response

        response_body_parts: list[bytes] = []
        async for chunk in response.body_iterator:  # type: ignore[union-attr]
            response_body_parts.append(chunk.encode("utf-8") if isinstance(chunk, str) else chunk)
        response_body = b"".join(response_body_parts)
        replayable = len(response_body) <= config.IDEMPOTENCY_MAX_RESPONSE_BYTES
        stored_body = (
            response_body.decode("utf-8", errors="replace") if replayable else
            '{"detail":"Request completed but its response cannot be replayed; read the resulting resource"}'
        )
        async with get_db() as db:
            await db.execute(
                "UPDATE idempotency_keys SET response_body = ?, status_code = ? "
                "WHERE idempotency_key = ? AND status_code IS NULL",
                (stored_body, response.status_code if replayable else 409, storage_key),
            )
            await db.commit()

        # Return a new Response with the same body/status/headers
        return Response(
            content=response_body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )
