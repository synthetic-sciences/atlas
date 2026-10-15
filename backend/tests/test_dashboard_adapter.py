"""HTTP account contract fixtures keep Atlas independent of a Dashboard tree."""

from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from atlas_graph.db.connection import get_db
from atlas_graph.integrations.dashboard import Dashboard
from atlas_graph.runtime import Host, configure


@pytest.fixture
async def accounts(client, monkeypatch):
    monkeypatch.setenv("ATLAS_MODE", "hosted")
    token = uuid4().hex
    first, second, workspace = str(uuid4()), str(uuid4()), str(uuid4())
    state = {
        "revoked": False,
        "broken": False,
        "redirect": False,
        "mismatched": False,
        "collaboration": True,
        "calls": [],
    }
    service = FastAPI()

    @service.get("/api/internal/atlas/identity")
    async def identity(request: Request):
        assert request.headers["x-atlas-service-token"] == token
        state["calls"].append(dict(request.headers))
        if state["redirect"]:
            return RedirectResponse("http://127.0.0.1/credential-collector")
        if state["broken"]:
            return JSONResponse(
                status_code=503, content={"detail": "Private account diagnostics"}
            )
        bearer = request.headers.get("authorization")
        if bearer not in {"Bearer first", "Bearer second"} or (
            bearer == "Bearer first" and state["revoked"]
        ):
            raise HTTPException(401, detail="Invalid or revoked key")
        requested = request.headers.get("x-organization-id")
        if requested and requested != workspace:
            raise HTTPException(403, detail={"code": "api_key_workspace_mismatch"})
        user = first if bearer == "Bearer first" else second
        return {
            "identity": {
                "user_id": user,
                "key_id": "fixture-key",
                "organization_id": workspace,
                "workspace_locked": True,
                "account_secret": "must-not-transfer",
            },
            "profile": {
                "user_id": second if state["mismatched"] else user,
                "display_name": "Researcher",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-02T00:00:00Z",
                "email": "private-account@example.test",
                "password_hash": "must-not-transfer",
            },
        }

    @service.get("/api/internal/atlas/collaboration/{owner}")
    async def capability(owner: str, request: Request):
        assert owner == first
        assert request.headers["x-atlas-service-token"] == token
        assert "authorization" not in request.headers
        return {"enabled": state["collaboration"], "label": "Account"}

    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=service))
    remote = Dashboard("http://127.0.0.1", token, client=http)
    configure(
        Host(
            authenticate=remote.authenticate,
            optional_auth=remote.optional_auth,
            collaboration=remote.collaboration_allowed,
            collaboration_label=remote.collaboration_label,
        )
    )
    try:
        yield state, remote, first, second, workspace
    finally:
        configure(Host())
        await remote.close()


async def test_hosted_identity_caches_only_graph_profile(client, accounts):
    state, _, first, _, workspace = accounts
    headers = {
        "Authorization": "Bearer first",
        "X-Organization-ID": workspace,
        "X-User-ID": str(uuid4()),
        "Idempotency-Key": "fixture-create",
    }
    created = await client.post(
        "/api/v1/projects", json={"title": "Hosted graph"}, headers=headers
    )
    assert created.status_code == 201, created.text
    assert len(state["calls"]) == 1
    assert state["calls"][0]["x-organization-id"] == workspace
    assert "x-user-id" not in state["calls"][0]
    async with get_db() as db:
        row = (
            await db.execute_fetchall("SELECT * FROM users WHERE user_id=?", (first,))
        )[0]
        assert row["email"] == f"{first}@atlas.invalid"
        assert row["display_name"] == "Researcher"
        cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        names = {row[0] for row in await cursor.fetchall()}
        assert not names.intersection(
            {"api_keys", "organizations", "credit_transactions"}
        )
    status = await client.get(
        "/api/v1/auth/status", headers={"Authorization": "Bearer first"}
    )
    assert status.status_code == 200
    assert status.json()["user"]["organization_id"] == workspace
    assert "private-account" not in status.text
    assert "must-not-transfer" not in status.text


async def test_hosted_identity_isolates_users_and_observes_revocation_before_replay(
    client, accounts
):
    state, *_ = accounts
    headers = {"Authorization": "Bearer first", "Idempotency-Key": "persisted-create"}
    payload = {"title": "Private graph"}
    created = await client.post("/api/v1/projects", json=payload, headers=headers)
    assert created.status_code == 201
    project = created.json()["project_id"]
    other = await client.get(
        f"/api/nodes/{project}/tree", headers={"Authorization": "Bearer second"}
    )
    assert other.status_code == 403
    replay = await client.post("/api/v1/projects", json=payload, headers=headers)
    assert replay.status_code == 201
    assert replay.json()["project_id"] == project
    state["revoked"] = True
    assert (
        await client.post("/api/v1/projects", json=payload, headers=headers)
    ).status_code == 401
    assert (
        await client.get(
            f"/api/nodes/{project}/tree", headers={"Authorization": "Bearer first"}
        )
    ).status_code == 401


async def test_hosted_identity_does_not_cache_between_requests_or_ignore_workspace_pin(
    client, accounts
):
    state, *_ = accounts
    assert (
        await client.get(
            "/api/v1/auth/status", headers={"Authorization": "Bearer first"}
        )
    ).status_code == 200
    assert (
        await client.get(
            "/api/v1/auth/status", headers={"Authorization": "Bearer first"}
        )
    ).status_code == 200
    assert len(state["calls"]) == 2
    mismatch = await client.post(
        "/api/v1/projects",
        json={"title": "Forbidden"},
        headers={"Authorization": "Bearer first", "X-Organization-ID": str(uuid4())},
    )
    assert mismatch.status_code == 403
    assert mismatch.json()["detail"]["code"] == "api_key_workspace_mismatch"
    assert (
        await client.get("/api/v1/auth/status", headers={"Authorization": ""})
    ).status_code == 401
    assert (await client.get("/api/v1/explore/graphs")).status_code == 404


@pytest.mark.parametrize("fault", ["broken", "redirect", "mismatched"])
async def test_hosted_identity_fails_closed_without_following_redirects(
    client, accounts, fault
):
    state, *_ = accounts
    state[fault] = True
    response = await client.post(
        "/api/v1/projects",
        json={"title": "Must not write"},
        headers={"Authorization": "Bearer first"},
    )
    assert response.status_code == 503
    assert "Private account diagnostics" not in response.text
    async with get_db() as db:
        assert (await db.execute_fetchall("SELECT COUNT(*) FROM nodes"))[0][0] == 0
        assert (await db.execute_fetchall("SELECT COUNT(*) FROM users"))[0][0] == 0


async def test_hosted_collaboration_observes_account_capability_changes(accounts):
    state, remote, first, *_ = accounts
    assert await remote.collaboration_allowed(None, first) is True
    assert await remote.collaboration_label(None, first) == "Account"
    state["collaboration"] = False
    assert await remote.collaboration_allowed(None, first) is False


@pytest.mark.parametrize(
    "url",
    [
        "http://account.example",
        "https://user:password@account.example",
        "https://account.example/private",
        "https://account.example?secret=value",
        "https://account.example#fragment",
    ],
)
def test_account_origin_rejects_credentials_redirect_paths_and_unencrypted_remote_hosts(
    url,
):
    with pytest.raises(ValueError, match="HTTPS origin"):
        Dashboard(url, uuid4().hex)


def test_hosted_entry_point_requires_explicit_mode_and_credentials(monkeypatch):
    from atlas_graph.hosted import create_app

    monkeypatch.setenv("ATLAS_MODE", "local")
    with pytest.raises(RuntimeError, match="ATLAS_MODE=hosted"):
        create_app()
    monkeypatch.setenv("ATLAS_MODE", "hosted")
    monkeypatch.delenv("ATLAS_SIGNING_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="own signing secret"):
        create_app()
    monkeypatch.setenv("ATLAS_SIGNING_SECRET", uuid4().hex)
    monkeypatch.setenv("ATLAS_ACCOUNT_URL", "https://accounts.example.test")
    monkeypatch.delenv("ATLAS_ACCOUNT_SERVICE_TOKEN", raising=False)
    with pytest.raises(ValueError, match="service credential"):
        create_app()
