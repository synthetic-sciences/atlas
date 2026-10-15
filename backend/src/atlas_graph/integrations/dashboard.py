"""Delegate account authority without importing or copying account storage."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from fastapi import HTTPException, Request
from pydantic import BaseModel, StrictBool, StrictStr, ValidationError

from atlas_graph.db.connection import get_db


class Identity(BaseModel):
    user_id: UUID
    key_id: StrictStr | None = None
    organization_id: UUID | None = None
    workspace_locked: StrictBool


class Profile(BaseModel):
    user_id: UUID
    display_name: StrictStr | None = None
    github_username: StrictStr | None = None
    avatar_url: StrictStr | None = None
    created_at: datetime
    updated_at: datetime


class Account(BaseModel):
    identity: Identity
    profile: Profile


class Collaboration(BaseModel):
    enabled: StrictBool
    label: StrictStr


class Dashboard:
    def __init__(
        self, url: str, token: str, *, client: httpx.AsyncClient | None = None
    ):
        parsed = urlsplit(url)
        if (
            not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or parsed.scheme not in {"http", "https"}
            or (
                parsed.scheme == "http"
                and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            )
        ):
            raise ValueError("Dashboard must use an HTTPS origin or loopback HTTP")
        if len(token) < 32:
            raise ValueError("An Atlas account service credential is required")
        self.url = url.rstrip("/")
        self.token = token
        self.client = client or httpx.AsyncClient(
            timeout=10, follow_redirects=False, trust_env=False
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def request(self, path: str, *, headers: dict | None = None) -> dict:
        try:
            response = await self.client.get(
                f"{self.url}/api/internal/atlas/{path}",
                headers={**(headers or {}), "X-Atlas-Service-Token": self.token},
                follow_redirects=False,
            )
        except httpx.HTTPError:
            raise HTTPException(503, detail="Account service unavailable") from None
        if response.status_code != 200:
            detail = None
            if response.status_code in {400, 401, 403, 404, 409, 422, 429}:
                try:
                    payload = response.json()
                    detail = (
                        payload.get("detail") if isinstance(payload, dict) else None
                    )
                except ValueError:
                    pass
            raise HTTPException(
                response.status_code if detail is not None else 503,
                detail=detail if detail is not None else "Account service unavailable",
                headers={"WWW-Authenticate": "Bearer"}
                if response.status_code == 401
                else None,
            )
        try:
            payload = response.json()
        except ValueError:
            raise HTTPException(
                503, detail="Invalid account service response"
            ) from None
        if not isinstance(payload, dict):
            raise HTTPException(503, detail="Invalid account service response")
        return payload

    async def authenticate(self, request: Request) -> dict:
        cached = getattr(request.state, "atlas_account_identity", None)
        if cached is not None:
            return cached
        authorization = request.headers.get("authorization", "")
        if (
            not authorization.lower().startswith("bearer ")
            or not authorization[7:].strip()
        ):
            raise HTTPException(
                401,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        headers = {"Authorization": authorization}
        organization = request.headers.get("x-organization-id")
        if organization:
            headers["X-Organization-ID"] = organization
        payload = await self.request("identity", headers=headers)
        try:
            account = Account.model_validate(payload)
        except ValidationError:
            raise HTTPException(
                503, detail="Invalid account service identity"
            ) from None
        if account.identity.user_id != account.profile.user_id:
            raise HTTPException(503, detail="Invalid account service identity")
        identity = account.identity.model_dump(mode="json")
        profile = account.profile
        async with get_db() as db:
            await db.execute(
                "INSERT INTO users (user_id,email,display_name,github_username,avatar_url,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?) ON CONFLICT (user_id) DO UPDATE SET "
                "email=excluded.email,display_name=excluded.display_name,github_username=excluded.github_username,"
                "avatar_url=excluded.avatar_url,updated_at=excluded.updated_at,deleted_at=NULL",
                (
                    identity["user_id"],
                    f"{identity['user_id']}@atlas.invalid",
                    profile.display_name,
                    profile.github_username,
                    profile.avatar_url,
                    profile.created_at.isoformat(),
                    profile.updated_at.isoformat(),
                ),
            )
            await db.commit()
        request.state.atlas_account_identity = identity
        return identity

    async def optional_auth(self, request: Request) -> dict | None:
        return (
            await self.authenticate(request)
            if request.headers.get("authorization")
            else None
        )

    async def collaboration(self, db, owner_id: str) -> Collaboration:
        payload = await self.request(f"collaboration/{UUID(owner_id)}")
        try:
            return Collaboration.model_validate(payload)
        except ValidationError:
            raise HTTPException(
                503, detail="Invalid account service capability"
            ) from None

    async def collaboration_allowed(self, db, owner_id: str) -> bool:
        return (await self.collaboration(db, owner_id)).enabled

    async def collaboration_label(self, db, owner_id: str) -> str:
        return (await self.collaboration(db, owner_id)).label
