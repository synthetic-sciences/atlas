"""Dependencies supplied by an embedding application or standalone adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable


@dataclass(frozen=True)
class Host:
    config: object | None = None
    database: Callable | None = None
    authenticate: Callable | None = None
    optional_auth: Callable | None = None
    browser_auth: Callable | None = None
    dependency_database: Callable | None = None
    collaboration: Callable[..., Awaitable[bool]] | None = None
    collaboration_label: Callable[..., Awaitable[str]] | None = None
    github: Callable[[], object] | None = None
    embeddings: Callable[[], object] | None = None
    billing_errors: Callable[[], tuple[type[Exception], ...]] | None = None
    errors: Callable | None = None
    mfa: Callable | None = None


_host = Host()


def configure(host: Host) -> None:
    global _host
    _host = host


def host() -> Host:
    return _host


async def collaboration_allowed(db, owner_id: str) -> bool:
    callback = _host.collaboration
    if callback is None:
        from atlas_graph import config

        return config.MODE == "local"
    return bool(await callback(db, owner_id))


async def collaboration_label(db, owner_id: str) -> str:
    callback = _host.collaboration_label
    return await callback(db, owner_id) if callback is not None else "Account"

