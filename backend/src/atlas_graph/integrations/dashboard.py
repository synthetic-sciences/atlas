"""Delegate account authority without importing or copying account storage."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from typing import Annotated
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import httpx
from fastapi import HTTPException, Request
from pydantic import BaseModel, Field, StrictBool, StrictInt, StrictStr, ValidationError

from atlas_graph.clients.github_client import GitHubError
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


class Connection(BaseModel):
    connected: StrictBool


class Commit(BaseModel):
    sha: str = Field(strict=True, pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


class Ref(BaseModel):
    object: Commit


class Embeddings(BaseModel):
    operation_id: str = Field(strict=True, pattern=r"^[0-9a-f]{64}$")
    model: StrictStr
    vectors: Annotated[
        list[
            Annotated[
                list[Annotated[float, Field(strict=True, allow_inf_nan=False)]],
                Field(min_length=1536, max_length=1536),
            ]
        ],
        Field(min_length=1, max_length=16),
    ]


class QueryEmbeddings(Embeddings):
    request_hash: str = Field(strict=True, pattern=r"^[0-9a-f]{64}$")


class UploadTicket(BaseModel):
    upload_id: UUID
    node_id: UUID
    batch_token: str = Field(strict=True, min_length=1, max_length=512)
    content_type: str = Field(strict=True, min_length=1, max_length=256)
    iat: StrictInt
    exp: StrictInt


class Query:
    def __init__(self, account: Dashboard, request: Request):
        self.account = account
        self.headers = account.headers(request)
        key = request.headers.get("idempotency-key")
        self.request_id = str(uuid5(
            NAMESPACE_URL, f"{request.method}:{request.url.path}:{key}",
        ) if key else uuid4())

    async def embed(self, text: str) -> tuple[list[float], None]:
        body = {"request_id": self.request_id, "text": text}
        payload = await self.account.request(
            "query/embeddings", method="POST", headers=self.headers,
            body=body, timeout=150,
        )
        try:
            parsed = QueryEmbeddings.model_validate(payload)
        except ValidationError:
            raise HTTPException(503, detail="Invalid query service response") from None
        fingerprint = hashlib.sha256(json.dumps(
            {"contract": "atlas-query-v1", "model": "openai/text-embedding-3-small", **body},
            sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        ).encode()).hexdigest()
        if (
            parsed.request_hash != fingerprint
            or parsed.model != "openai/text-embedding-3-small"
            or len(parsed.vectors) != 1
        ):
            raise HTTPException(503, detail="Invalid query service response")
        return parsed.vectors[0], None


class Repository:
    def __init__(self, account: Dashboard, headers: dict[str, str]):
        self.account = account
        self.headers = headers

    async def call(self, operation: str, repo: str, **fields: str) -> dict:
        try:
            return await self.account.request(
                "repository",
                method="POST",
                headers=self.headers,
                body={"operation": operation, "repo": repo, **fields},
            )
        except HTTPException as error:
            if (
                isinstance(error.detail, dict)
                and error.detail.get("code") == "github_error"
            ):
                raise GitHubError(
                    error.status_code,
                    error.detail.get("message", "GitHub request failed"),
                ) from None
            raise

    async def is_connected(self, repo: str) -> bool:
        payload = await self.call("status", repo)
        try:
            return Connection.model_validate(payload).connected
        except ValidationError:
            raise HTTPException(
                503, detail="Invalid repository service response"
            ) from None

    async def create_ref(self, repo: str, ref: str, sha: str) -> dict:
        return self.ref(await self.call("create_ref", repo, ref=ref, sha=sha))

    async def get_ref(self, repo: str, ref: str) -> dict:
        return self.ref(await self.call("ref", repo, ref=ref))

    async def get_commit(self, repo: str, sha: str) -> dict:
        payload = await self.call("commit", repo, sha=sha)
        try:
            return Commit.model_validate(payload).model_dump()
        except ValidationError:
            raise HTTPException(
                503, detail="Invalid repository service response"
            ) from None

    @staticmethod
    def ref(payload: dict) -> dict:
        try:
            return Ref.model_validate(payload).model_dump()
        except ValidationError:
            raise HTTPException(
                503, detail="Invalid repository service response"
            ) from None


class Dashboard:
    def __init__(
        self,
        url: str,
        token: str,
        *,
        client: httpx.AsyncClient | None = None,
        index_token: str = "",
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
        self.index_token = index_token
        self.client = client or httpx.AsyncClient(
            timeout=10, follow_redirects=False, trust_env=False
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def request(
        self,
        path: str,
        *,
        headers: dict | None = None,
        method: str = "GET",
        body: dict | None = None,
        account: bool = True,
        timeout: float = 10,
    ) -> dict:
        try:
            response = await self.client.request(
                method,
                f"{self.url}/api/internal/atlas/{path}",
                headers={
                    **(headers or {}),
                    **({"X-Atlas-Service-Token": self.token} if account else {}),
                },
                json=body,
                follow_redirects=False,
                timeout=timeout,
            )
        except httpx.HTTPError:
            raise HTTPException(503, detail="Account service unavailable") from None
        if response.status_code != 200:
            detail = None
            if response.status_code in {400, 401, 402, 403, 404, 409, 410, 422, 429}:
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

    @staticmethod
    def headers(request: Request) -> dict[str, str]:
        headers = {"Authorization": request.headers.get("authorization", "")}
        organization = request.headers.get("x-organization-id")
        if organization:
            headers["X-Organization-ID"] = organization
        return headers

    def repository(self, request: Request) -> Repository:
        return Repository(self, self.headers(request))

    def query(self, request: Request) -> Query:
        return Query(self, request)

    async def upload_ticket(self, ticket: str) -> dict:
        if len(ticket) > 16_384:
            raise HTTPException(403, detail="Invalid upload ticket")
        payload = await self.request("upload-ticket", method="POST", body={"ticket": ticket})
        try:
            return UploadTicket.model_validate(payload).model_dump(mode="json")
        except ValidationError:
            raise HTTPException(503, detail="Invalid upload ticket service response") from None

    async def index_node(self, node: dict, chunks: list[dict]) -> list[list[float]]:
        if not chunks:
            return []
        if len(self.index_token) < 32:
            from atlas_graph.clients._direct_embed import ConfigurationError

            raise ConfigurationError("The hosted indexing adapter is not configured")
        result = []
        for offset in range(0, len(chunks), 16):
            body = {
                "owner_id": str(UUID(node["owner_user_id"])),
                "node_id": str(UUID(node["node_id"])),
                "revision": int(node["revision"]),
                "texts": [chunk["text"] for chunk in chunks[offset : offset + 16]],
            }
            payload = await self.request(
                "index/embeddings",
                method="POST",
                body=body,
                headers={"X-Atlas-Index-Token": self.index_token},
                account=False,
                timeout=150,
            )
            try:
                parsed = Embeddings.model_validate(payload)
            except ValidationError:
                raise HTTPException(
                    503, detail="Invalid indexing service response"
                ) from None
            fingerprint = hashlib.sha256(
                json.dumps(
                    {
                        "contract": "atlas-index-v1",
                        "model": "openai/text-embedding-3-small",
                        **body,
                    },
                    sort_keys=True,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            if (
                parsed.operation_id != fingerprint
                or parsed.model != "openai/text-embedding-3-small"
                or len(parsed.vectors) != len(body["texts"])
            ):
                raise HTTPException(503, detail="Invalid indexing service response")
            result.extend(parsed.vectors)
        return result

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
