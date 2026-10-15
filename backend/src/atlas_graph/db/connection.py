"""Graph-only database lifecycle with an optional embedding-host connection."""

from __future__ import annotations

from contextlib import asynccontextmanager
from importlib.resources import files

import aiosqlite

from atlas_graph import config
from atlas_graph.db.postgres import PgConnectionWrapper
from atlas_graph.runtime import host

_pool = None


async def init_db() -> None:
    global _pool
    if host().database is not None:
        raise RuntimeError("The embedding host owns its database lifecycle")
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.BLOBS_DIR.mkdir(parents=True, exist_ok=True)
    if config.USE_POSTGRES:
        import asyncpg

        if _pool is None:
            _pool = await asyncpg.create_pool(config.DATABASE_URL, min_size=1, max_size=10)
        async with _pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute("SELECT pg_advisory_xact_lock(28048739301404496)")
                await connection.execute("CREATE TABLE IF NOT EXISTS atlas_schema_versions (version INTEGER PRIMARY KEY)")
                installed = await connection.fetchval("SELECT version FROM atlas_schema_versions WHERE version = 1")
                if installed is None:
                    schema = files("atlas_graph.db").joinpath("schema.pg.sql").read_text()
                    await connection.execute(schema)
                    await connection.execute("INSERT INTO atlas_schema_versions (version) VALUES (1)")
        return
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute("PRAGMA journal_mode = WAL")
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("CREATE TABLE IF NOT EXISTS atlas_schema_versions (version INTEGER PRIMARY KEY)")
        cursor = await db.execute("SELECT version FROM atlas_schema_versions WHERE version = 1")
        if await cursor.fetchone() is None:
            schema = files("atlas_graph.db").joinpath("schema.sql").read_text()
            await db.executescript(schema)
            await db.execute("INSERT INTO atlas_schema_versions (version) VALUES (1)")
        await db.commit()


@asynccontextmanager
async def get_db():
    provider = host().database
    if provider is not None:
        async with provider() as db:
            yield db
        return
    if config.USE_POSTGRES:
        if _pool is None:
            raise RuntimeError("Atlas database is not initialized")
        async with _pool.acquire(timeout=10) as connection:
            yield PgConnectionWrapper(connection)
        return
    async with aiosqlite.connect(config.DB_PATH, timeout=15) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON")
        yield db


async def close_db() -> None:
    global _pool
    pool = _pool
    _pool = None
    if pool is not None:
        await pool.close()

