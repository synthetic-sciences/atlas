"""Graph-only database lifecycle with an optional embedding-host connection."""

from __future__ import annotations

from contextlib import asynccontextmanager
from importlib.resources import files
import re
import sqlite3

import aiosqlite

from atlas_graph import config
from atlas_graph.db.postgres import PgConnectionWrapper
from atlas_graph.runtime import host

_pool = None
MIGRATIONS = ("schema", "index")


async def _sqlite_script(db, script: str) -> None:
    # executescript commits an existing transaction before running. Execute
    # complete statements ourselves so the migration lock and DDL stay atomic.
    statement = ""
    for line in script.splitlines(keepends=True):
        if not statement and (not line.strip() or line.lstrip().startswith("--")):
            continue
        statement += line
        if sqlite3.complete_statement(statement):
            cursor = await db.execute(statement)
            await cursor.close()
            statement = ""
    if statement.strip():
        raise RuntimeError("Incomplete SQLite migration statement")


async def init_db() -> None:
    global _pool
    if host().database is not None:
        raise RuntimeError("The embedding host owns its database lifecycle")
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.BLOBS_DIR.mkdir(parents=True, exist_ok=True)
    if config.USE_POSTGRES:
        import asyncpg

        namespace = config.DATABASE_SCHEMA
        if not re.fullmatch(r"[a-z_][a-z0-9_]*", namespace):
            raise RuntimeError("ATLAS_DATABASE_SCHEMA must be a PostgreSQL identifier")
        try:
            maximum = int(config.PG_POOL_MAX)
        except (ValueError, TypeError):
            raise RuntimeError("ATLAS_PG_POOL_MAX must be between 1 and 32") from None
        if not 1 <= maximum <= 32:
            raise RuntimeError("ATLAS_PG_POOL_MAX must be between 1 and 32")
        if _pool is None:
            _pool = await asyncpg.create_pool(
                config.DATABASE_URL,
                min_size=1,
                max_size=maximum,
                timeout=10,
                command_timeout=60,
                server_settings={"search_path": f'"{namespace}", public'},
            )
        try:
            async with _pool.acquire() as connection:
                if await connection.fetchval("SELECT current_schema()") != namespace:
                    raise RuntimeError(
                        "The configured Atlas schema must already exist and be accessible"
                    )
                async with connection.transaction():
                    await connection.execute(
                        "SELECT pg_advisory_xact_lock(28048739301404496)"
                    )
                    await connection.execute(
                        "CREATE TABLE IF NOT EXISTS atlas_schema_versions (version INTEGER PRIMARY KEY)"
                    )
                    for version, name in enumerate(MIGRATIONS, start=1):
                        installed = await connection.fetchval(
                            "SELECT version FROM atlas_schema_versions WHERE version=$1",
                            version,
                        )
                        if installed is not None:
                            continue
                        schema = (
                            files("atlas_graph.db")
                            .joinpath(f"{name}.pg.sql")
                            .read_text()
                        )
                        if namespace != "public":
                            schema = schema.replace(
                                "public.", f'"{namespace}".'
                            ).replace(f'"{namespace}".vector', "public.vector")
                        await connection.execute(schema)
                        await connection.execute(
                            "INSERT INTO atlas_schema_versions (version) VALUES ($1)",
                            version,
                        )
        except BaseException:
            await close_db()
            raise
        return
    async with aiosqlite.connect(config.DB_PATH, timeout=15) as db:
        await db.execute("PRAGMA journal_mode = WAL")
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("BEGIN IMMEDIATE")
        try:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS atlas_schema_versions (version INTEGER PRIMARY KEY)"
            )
            for version, name in enumerate(MIGRATIONS, start=1):
                cursor = await db.execute(
                    "SELECT version FROM atlas_schema_versions WHERE version=?", (version,)
                )
                installed = await cursor.fetchone()
                await cursor.close()
                if installed is not None:
                    continue
                await _sqlite_script(db, files("atlas_graph.db").joinpath(f"{name}.sql").read_text())
                await db.execute("INSERT INTO atlas_schema_versions (version) VALUES (?)", (version,))
            await db.commit()
        except BaseException:
            await db.rollback()
            raise


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
