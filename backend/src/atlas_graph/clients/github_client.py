"""Thin async GitHub REST client used by the tracer service.

Only the minimal surface area required by Knowledge v0 is implemented:

- ``search_code``  -> ``GET /search/code``
- ``glob_files``   -> ``GET /search/code`` with a ``filename:`` qualifier
- ``read_file``    -> ``GET /repos/{owner}/{repo}/contents/{path}``
- ``tree``         -> ``GET /repos/{owner}/{repo}/git/trees/{sha}``

Authentication is optional.  When ``GITHUB_TOKEN`` is set in the
environment (see ``app.config.GITHUB_TOKEN``) a ``Bearer`` header is
attached; otherwise the client falls back to unauthenticated calls,
which are aggressively rate-limited by GitHub.

The client is rate-limit aware: on HTTP 429 (secondary rate limits) or
403 with the "rate limit" message, it retries with exponential backoff.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
from typing import Any

import httpx

from atlas_graph import config

logger = logging.getLogger(__name__)


GITHUB_API_BASE = "https://api.github.com"
DEFAULT_TIMEOUT = 30.0
MAX_RETRIES = 3
# Base backoff in seconds.  Tests override this to 0 for fast failure.
RETRY_BACKOFF_BASE = 1.0


# ---------------------------------------------------------------------------
# Shared httpx.AsyncClient (avoids TCP+TLS handshake on every GitHub call).
# ---------------------------------------------------------------------------

_http_client: httpx.AsyncClient | None = None
_http_client_lock = asyncio.Lock()


async def _get_http() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        async with _http_client_lock:
            if _http_client is None:
                _http_client = httpx.AsyncClient(
                    timeout=DEFAULT_TIMEOUT,
                    limits=httpx.Limits(
                        max_keepalive_connections=10,
                        max_connections=20,
                        keepalive_expiry=30.0,
                    ),
                )
    return _http_client


async def close_http() -> None:
    global _http_client
    if _http_client is not None:
        client = _http_client
        _http_client = None
        await client.aclose()


def _reset_http_for_tests() -> None:
    global _http_client
    _http_client = None


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class GitHubError(RuntimeError):
    """Raised when GitHub returns a non-retryable error."""

    def __init__(self, status: int, message: str):
        super().__init__(f"GitHub API error {status}: {message}")
        self.status = status
        self.message = message


class GitHubRateLimitError(GitHubError):
    """Raised when retries have been exhausted on a rate-limit response."""

    def __init__(self, message: str = "GitHub rate limit exceeded"):
        super().__init__(429, message)


# ---------------------------------------------------------------------------
# Internal HTTP helper
# ---------------------------------------------------------------------------


def _headers(
    auth_token: str | None = None,
    *,
    server_token_fallback: bool = True,
) -> dict[str, str]:
    """Build request headers, attaching a Bearer token when available.

    Precedence:
      1. ``auth_token`` explicitly passed by caller (per-user token).
      2. ``GITHUB_TOKEN`` env (backend-wide, public-read fallback).
      3. No auth (unauthenticated public-only calls).

    Set ``server_token_fallback=False`` to forbid step 2 entirely - the
    public, no-auth code-read path uses this so a misconfigured
    private-scoped ``GITHUB_TOKEN`` can never expose a private repo through
    a "public" node. With no per-user token, that path stays unauthenticated.
    """
    headers: dict[str, str] = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "thesis-backend/0.1 (+https://github.com)",
    }
    token = auth_token or ""
    if not token and server_token_fallback:
        token = getattr(config, "GITHUB_TOKEN", "") or os.environ.get("GITHUB_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _is_rate_limited(resp: httpx.Response) -> bool:
    """Return True if the response indicates a rate-limit condition."""
    if resp.status_code == 429:
        return True
    if resp.status_code == 403:
        # GitHub returns 403 for both forbidden and secondary rate limits.
        body_lower = ""
        try:
            body_lower = (resp.text or "").lower()
        except Exception:
            body_lower = ""
        if "rate limit" in body_lower or "abuse" in body_lower:
            return True
        # Header-based primary limit probe.
        remaining = resp.headers.get("X-RateLimit-Remaining")
        if remaining == "0":
            return True
    return False


async def _request(
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    max_retries: int = MAX_RETRIES,
    backoff_base: float | None = None,
    auth_token: str | None = None,
    server_token_fallback: bool = True,
) -> dict[str, Any] | list[Any]:
    """Issue an HTTP request against the GitHub API with rate-limit retries.

    Pass ``auth_token`` to use a per-user GitHub token; otherwise the
    request falls back to the backend-wide ``GITHUB_TOKEN`` (public-read
    only) or unauthenticated. ``json_body`` is sent for write methods
    (e.g. POST /git/refs). Set ``server_token_fallback=False`` to forbid the
    backend-wide token (public, no-auth code-read path).
    """
    backoff = RETRY_BACKOFF_BASE if backoff_base is None else backoff_base

    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            hc = await _get_http()
            request_kwargs: dict[str, Any] = {
                "params": params,
                "headers": _headers(
                    auth_token, server_token_fallback=server_token_fallback
                ),
            }
            if json_body is not None:
                request_kwargs["json"] = json_body
            resp = await hc.request(method, url, **request_kwargs)
        except httpx.HTTPError as exc:  # pragma: no cover - network errors
            last_exc = exc
            if attempt >= max_retries:
                raise GitHubError(0, str(exc)) from exc
            await asyncio.sleep(backoff * (2 ** attempt))
            continue

        if _is_rate_limited(resp):
            if attempt >= max_retries:
                raise GitHubRateLimitError(
                    f"rate limited after {attempt + 1} attempts: {resp.text[:200]}"
                )
            delay = backoff * (2 ** attempt)
            logger.warning(
                "GitHub rate limit on %s (status=%d), retrying in %.2fs",
                url, resp.status_code, delay,
            )
            await asyncio.sleep(delay)
            continue

        if resp.status_code >= 400:
            raise GitHubError(resp.status_code, resp.text[:500])

        try:
            return resp.json()
        except ValueError:
            return {}

    # Should never get here but keep mypy happy.
    if last_exc is not None:
        raise GitHubError(0, str(last_exc))
    raise GitHubError(0, "unknown request failure")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def search_code(
    query: str,
    repo: str | None = None,
    per_page: int = 30,
    *,
    auth_token: str | None = None,
) -> dict[str, Any]:
    """Search code on GitHub.

    Parameters
    ----------
    query : str
        Free-form search query (GitHub code-search syntax supported).
    repo : str | None
        Optional ``owner/name`` restriction.
    per_page : int
        Max results per page (1..100).

    Returns
    -------
    dict
        The raw GitHub search response: ``{"total_count", "items": [...]}``.
    """
    if not query or not query.strip():
        raise ValueError("query must be a non-empty string")

    q = query.strip()
    if repo:
        q = f"{q} repo:{repo}"

    per_page = max(1, min(int(per_page), 100))
    data = await _request(
        "GET",
        f"{GITHUB_API_BASE}/search/code",
        params={"q": q, "per_page": per_page},
        auth_token=auth_token,
    )
    if not isinstance(data, dict):
        return {"total_count": 0, "items": []}
    return data


async def glob_files(
    owner_repo: str,
    pattern: str,
    ref: str = "HEAD",  # noqa: ARG001 - kept for API symmetry
    *,
    auth_token: str | None = None,
) -> list[dict[str, Any]]:
    """Search for files matching a filename pattern inside a repo.

    This uses GitHub's ``filename:`` qualifier.  For full glob fidelity a
    worker would clone the repo, but Knowledge v0 is happy with filename
    substring matches.
    """
    if "/" not in owner_repo:
        raise ValueError("owner_repo must look like 'owner/name'")

    # Normalise common glob patterns to GitHub's filename qualifier.
    clean_pattern = pattern.strip().strip("*")
    clean_pattern = clean_pattern.lstrip("/")
    if "/" in clean_pattern:
        clean_pattern = clean_pattern.rsplit("/", 1)[-1]
    if not clean_pattern:
        clean_pattern = pattern.strip()

    q = f"filename:{clean_pattern} repo:{owner_repo}"
    data = await _request(
        "GET",
        f"{GITHUB_API_BASE}/search/code",
        params={"q": q, "per_page": 30},
        auth_token=auth_token,
    )
    if not isinstance(data, dict):
        return []
    return list(data.get("items") or [])


async def read_file(
    owner_repo: str,
    path: str,
    ref: str = "HEAD",
    line_start: int | None = None,
    line_end: int | None = None,
    *,
    auth_token: str | None = None,
    server_token_fallback: bool = True,
) -> dict[str, Any]:
    """Read a file from a GitHub repo.

    Returns a dict with ``content`` (decoded text), ``sha``, ``path``,
    ``ref``, and ``line_start``/``line_end`` when slicing.
    """
    if "/" not in owner_repo:
        raise ValueError("owner_repo must look like 'owner/name'")

    owner, name = owner_repo.split("/", 1)
    data = await _request(
        "GET",
        f"{GITHUB_API_BASE}/repos/{owner}/{name}/contents/{path.lstrip('/')}",
        params={"ref": ref} if ref else None,
        auth_token=auth_token,
        server_token_fallback=server_token_fallback,
    )
    if not isinstance(data, dict):
        raise GitHubError(0, "unexpected response for read_file")

    encoding = data.get("encoding", "")
    raw = data.get("content") or ""
    if encoding == "base64":
        try:
            content_bytes = base64.b64decode(raw)
            content = content_bytes.decode("utf-8", errors="replace")
        except Exception:  # pragma: no cover - defensive
            content = raw
    else:
        content = raw

    # Optional 1-indexed line slicing.
    if line_start is not None or line_end is not None:
        lines = content.splitlines()
        start = max(1, line_start or 1)
        end = line_end if line_end is not None else len(lines)
        end = min(end, len(lines))
        content = "\n".join(lines[start - 1 : end])
    else:
        start = None
        end = None

    return {
        "content": content,
        "sha": data.get("sha"),
        "path": data.get("path", path),
        "ref": ref,
        "line_start": start,
        "line_end": end,
        "size": data.get("size"),
    }


async def tree(
    owner_repo: str,
    path: str = "",
    ref: str = "HEAD",
    *,
    auth_token: str | None = None,
    server_token_fallback: bool = True,
) -> list[dict[str, Any]]:
    """List files/directories under ``path`` in a GitHub repo.

    Uses the ``contents`` endpoint for simplicity and pagination avoidance.
    """
    if "/" not in owner_repo:
        raise ValueError("owner_repo must look like 'owner/name'")

    owner, name = owner_repo.split("/", 1)
    path = (path or "").lstrip("/")
    data = await _request(
        "GET",
        f"{GITHUB_API_BASE}/repos/{owner}/{name}/contents/{path}",
        params={"ref": ref} if ref else None,
        auth_token=auth_token,
        server_token_fallback=server_token_fallback,
    )

    if isinstance(data, list):
        entries = data
    elif isinstance(data, dict):
        entries = [data]
    else:
        entries = []

    return [
        {
            "name": entry.get("name"),
            "path": entry.get("path"),
            "type": entry.get("type"),
            "sha": entry.get("sha"),
            "size": entry.get("size"),
        }
        for entry in entries
    ]


async def create_ref(
    owner_repo: str,
    ref: str,
    sha: str,
    *,
    auth_token: str | None = None,
) -> dict[str, Any]:
    """Create a git ref pointing at an existing remote commit.

    Used to pin a node's captured commit as an immutable tag
    (``refs/tags/atlas/<slug>-r<rev>``) so the exact code state stays
    reachable even if the branch later moves or is force-pushed.

    ``sha`` must already exist on the remote (push first). GitHub returns
    422 when the ref already exists; callers typically treat that as
    "already pinned". Requires a token with write access to the repo.
    """
    if "/" not in owner_repo:
        raise ValueError("owner_repo must look like 'owner/name'")
    if not sha:
        raise ValueError("sha is required")
    full_ref = ref if ref.startswith("refs/") else f"refs/{ref}"

    owner, name = owner_repo.split("/", 1)
    data = await _request(
        "POST",
        f"{GITHUB_API_BASE}/repos/{owner}/{name}/git/refs",
        json_body={"ref": full_ref, "sha": sha},
        auth_token=auth_token,
    )
    return data if isinstance(data, dict) else {}


async def get_ref(
    owner_repo: str,
    ref: str,
    *,
    auth_token: str | None = None,
) -> dict[str, Any]:
    """Read a git ref from GitHub.

    ``ref`` can be ``refs/tags/x``, ``tags/x``, ``heads/main``, or a raw tag /
    branch name. Used by reproduce checks to confirm a pinned tag is actually
    reachable on the remote.
    """
    if "/" not in owner_repo:
        raise ValueError("owner_repo must look like 'owner/name'")
    clean = ref
    if clean.startswith("refs/"):
        clean = clean[len("refs/") :]
    if not (clean.startswith("tags/") or clean.startswith("heads/")):
        clean = f"tags/{clean}"
    owner, name = owner_repo.split("/", 1)
    data = await _request(
        "GET",
        f"{GITHUB_API_BASE}/repos/{owner}/{name}/git/ref/{clean}",
        auth_token=auth_token,
    )
    return data if isinstance(data, dict) else {}


async def get_commit(
    owner_repo: str,
    sha: str,
    *,
    auth_token: str | None = None,
) -> dict[str, Any]:
    """Read a commit object by SHA, proving it is reachable in the repo."""
    if "/" not in owner_repo:
        raise ValueError("owner_repo must look like 'owner/name'")
    if not sha:
        raise ValueError("sha is required")
    owner, name = owner_repo.split("/", 1)
    data = await _request(
        "GET",
        f"{GITHUB_API_BASE}/repos/{owner}/{name}/git/commits/{sha}",
        auth_token=auth_token,
    )
    return data if isinstance(data, dict) else {}
