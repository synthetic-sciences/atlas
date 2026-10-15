"""Graph identities come from explicit local or hosting adapters."""

from datetime import datetime, timezone
import os
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid5

from fastapi import Depends, HTTPException, Request

from atlas_graph import config
from atlas_graph.db.connection import get_db as database
from atlas_graph.runtime import host

LOCAL_USER_ID = str(uuid5(NAMESPACE_URL, "https://atlas.local/owner"))


def require_local_connection(request) -> None:
    address = request.client.host if request.client else ""
    if address not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(status_code=403, detail="Local Atlas accepts loopback connections only")
    if request.url.hostname not in {"127.0.0.1", "::1", "localhost", "testserver"}:
        raise HTTPException(status_code=403, detail="Invalid local Atlas host")
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).hostname not in {"127.0.0.1", "::1", "localhost"}:
        raise HTTPException(status_code=403, detail="Invalid local Atlas origin")


async def get_current_user(request: Request) -> dict:
    callback = host().authenticate
    if callback is not None:
        return await callback(request)
    if config.MODE != "local":
        raise HTTPException(status_code=503, detail="An identity adapter is not configured")
    require_local_connection(request)
    expected = os.environ.get("ATLAS_LOCAL_TOKEN", "local")
    if request.headers.get("authorization") != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="Local Atlas authentication required")
    now = datetime.now(timezone.utc).isoformat()
    async with database() as db:
        await db.execute(
            "INSERT INTO users (user_id,email,display_name,created_at,updated_at) VALUES (?,?,?,?,?) ON CONFLICT (user_id) DO NOTHING",
            (LOCAL_USER_ID, "owner@atlas.local", "Local researcher", now, now),
        )
        await db.commit()
    return {"user_id": LOCAL_USER_ID, "key_id": "local", "email": "owner@atlas.local"}


async def optional_auth(request: Request) -> dict | None:
    callback = host().optional_auth
    if callback is not None:
        return await callback(request)
    if not request.headers.get("authorization"):
        return None
    return await get_current_user(request)


async def get_verified_browser_user(user: dict = Depends(get_current_user)) -> dict:
    if user.get("key_id"):
        raise HTTPException(status_code=403, detail={"code": "verified_session_required"})
    return user


async def get_db():
    async with database() as db:
        yield db


# Retain dependency identity so an embedding application's existing FastAPI
# overrides and request-scoped database fixtures continue to apply.
get_current_user = host().authenticate or get_current_user
optional_auth = host().optional_auth or optional_auth
get_verified_browser_user = host().browser_auth or get_verified_browser_user
get_db = host().dependency_database or get_db

