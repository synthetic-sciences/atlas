"""Standalone graph API. Hosting products use the same routers and services."""

from contextlib import asynccontextmanager
import asyncio
import json

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from atlas_graph import config
from atlas_graph.db.connection import close_db, get_db, init_db
from atlas_graph.dependencies import get_current_user, require_local_connection
from atlas_graph.middleware.idempotency import IdempotencyMiddleware
from atlas_graph.realtime.websocket_server import manager
from atlas_graph.runtime import host
from atlas_graph.routes import artifacts, audit, browse, campaigns, competitions, core, export_import, nodes, runs, semantics, sharing, tags, users


@asynccontextmanager
async def lifespan(app: FastAPI):
    shutdown = host().shutdown
    indexer = None
    try:
        await init_db()
        if config.INDEXING_ENABLED:
            from atlas_graph.services.index_jobs import Indexer

            indexer = Indexer()
            await indexer.start()
        yield
    finally:
        try:
            try:
                if indexer is not None:
                    await indexer.stop()
            finally:
                await close_db()
        finally:
            if shutdown is not None:
                await shutdown()


app = FastAPI(title="Atlas graph API", lifespan=lifespan, docs_url="/docs" if config.MODE == "local" else None, redoc_url=None, openapi_url="/openapi.json" if config.MODE == "local" else None)
app.add_middleware(IdempotencyMiddleware)
app.add_middleware(CORSMiddleware, allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?", allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"], allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Thesis-Artifact-Filename"])


@app.middleware("http")
async def boundaries(request, call_next):
    if config.MODE == "local":
        try:
            require_local_connection(request)
        except HTTPException as error:
            return JSONResponse(status_code=error.status_code, content={"detail": error.detail})
    path = request.url.path
    public = path.startswith(("/api/nodes/explore", "/api/researchers", "/api/users/", "/api/competitions", "/api/v1/explore", "/api/v1/researchers", "/api/v1/competitions"))
    if public and not config.PUBLIC_GRAPHS_ENABLED:
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Frame-Options"] = "DENY"
    return response


for module in [nodes, tags, sharing, artifacts, audit, export_import, browse, campaigns, competitions, users, runs, semantics]:
    app.include_router(module.router)
app.include_router(core.router, prefix="/api/v1")


@app.get("/api/health")
@app.get("/api/health/db")
async def health():
    async with get_db() as db:
        await db.execute("SELECT 1")
    return {"status": "ok", "service": "atlas", "database_backend": "postgres" if config.USE_POSTGRES else "sqlite"}


@app.get("/api/v1/status")
async def service_status():
    return {"ok": True, "service": "atlas", "mode": config.MODE}


@app.get("/api/v1/auth/status")
async def auth_status(user: dict = Depends(get_current_user)):
    return {"authenticated": True, "user": user, "service": "atlas"}


@app.websocket("/api/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        if websocket.query_params.get("token"):
            await websocket.close(code=4001)
            return
        if config.MODE == "local":
            require_local_connection(websocket)
        data = await asyncio.wait_for(websocket.receive_json(), timeout=10)
        if not isinstance(data, dict) or data.get("type") != "auth" or not isinstance(data.get("token"), str):
            await websocket.close(code=4001)
            return
        scope = {**websocket.scope, "type": "http", "method": "GET", "headers": [*[(key,value) for key,value in websocket.scope.get("headers",[]) if key.lower() != b"authorization"], (b"authorization", f"Bearer {data['token']}".encode())]}
        from starlette.requests import Request

        user = await get_current_user(Request(scope))
        if not manager.register(websocket, user["user_id"]):
            await websocket.close(code=4029)
            return
        try:
            await websocket.send_json({"type": "connected", "user_id": user["user_id"]})
            while True:
                message = await websocket.receive_json()
                if not isinstance(message, dict):
                    await websocket.close(code=4001)
                    return
                if message.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
                if message.get("type") == "subscribe":
                    from atlas_graph.auth.access_check import check_node_access

                    node_id = str(message.get("node_id") or "")
                    async with get_db() as db:
                        allowed = await check_node_access(db, user["user_id"], node_id)
                    await websocket.send_json({"type": "subscribed", "node_id": node_id} if allowed else {"type": "error", "code": "access_denied", "node_id": node_id})
        finally:
            manager.disconnect(websocket, user["user_id"])
    except WebSocketDisconnect:
        return
    except (HTTPException, asyncio.TimeoutError, ValueError):
        await websocket.close(code=4001)

