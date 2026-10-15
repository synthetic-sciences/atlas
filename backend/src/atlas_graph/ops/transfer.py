"""Rehearse graph data transfer into a fresh, isolated PostgreSQL target."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from urllib.parse import urlsplit

import asyncpg

TABLES = (
    "users",
    "competitions",
    "nodes",
    "node_edges",
    "project_dedupe_keys",
    "artifacts",
    "audit_events",
    "campaign_budgets",
    "competition_entries",
    "graph_stars",
    "knowledge_sources",
    "knowledge_chunks",
    "node_access_rules",
    "research_log",
    "stage_leases",
    "tags",
    "tag_assignments",
    "tag_history",
    "artifact_upload_batches",
)
REFERENCES = (
    ("nodes", "owner_user_id"),
    ("project_dedupe_keys", "owner_user_id"),
    ("node_access_rules", "user_id"),
    ("graph_stars", "user_id"),
    ("knowledge_sources", "owner_user_id"),
    ("stage_leases", "user_id"),
    ("campaign_budgets", "organizer_user_id"),
    ("campaign_budgets", "participant_user_id"),
    ("audit_events", "actor_user_id"),
    ("competition_entries", "user_id"),
)
PROFILE = (
    "user_id",
    "email",
    "display_name",
    "github_username",
    "avatar_url",
    "created_at",
    "updated_at",
    "deleted_at",
)


def fingerprint(rows: list[str]) -> str:
    # PostgreSQL emits canonical jsonb text. Keep it intact: decoding numeric
    # JSON through Python floats would silently round customer measurements.
    hashes = sorted(hashlib.sha256(row.encode()).digest() for row in rows)
    return hashlib.sha256(b"".join(hashes)).hexdigest()


async def transfer(
    source: asyncpg.Connection,
    target: asyncpg.Connection,
    *,
    source_schema: str = "public",
    target_schema: str = "public",
) -> dict:
    """Copy a consistent graph snapshot, preserving IDs and validating every row.

    The caller supplies a fresh graph schema. Existing target data is never
    replaced. Shared account idempotency records cannot be classified by their
    one-way scope hashes, so they require an authenticated legacy replay bridge.
    """
    if any(
        not re.fullmatch(r"[a-z_][a-z0-9_]*", name)
        for name in (source_schema, target_schema)
    ):
        raise ValueError("Graph schemas must be PostgreSQL identifiers")
    origin = f'"{source_schema}"'
    destination = f'"{target_schema}"'
    identities = [
        await connection.fetchrow(
            "SELECT inet_server_addr(),inet_server_port(),current_database()"
        )
        for connection in (source, target)
    ]
    if any(not row[2].startswith("atlas_graph_") for row in identities):
        raise ValueError("This rehearsal accepts isolated atlas_graph_* databases only")
    if identities[0] == identities[1] and source_schema == target_schema:
        raise ValueError("Source and target must use different databases or schemas")
    names = {
        row[0]
        for row in await target.fetch(
            "SELECT table_name FROM information_schema.tables WHERE table_schema=$1 AND table_type='BASE TABLE'",
            target_schema,
        )
    }
    required = {*TABLES, "idempotency_keys", "atlas_schema_versions"}
    if names != required:
        raise ValueError("Target must contain only the initialized graph schema")
    report = {
        "tables": {},
        "excluded": [
            "account credentials",
            "organizations",
            "Wallet",
            "telemetry",
            "shared idempotency responses",
        ],
        "production_ready": False,
        "remaining_gate": "Authenticated legacy idempotency replay, blob transfer, and writer fencing must be rehearsed before cutover",
    }
    async with (
        source.transaction(isolation="repeatable_read", readonly=True),
        target.transaction(),
    ):
        await source.execute("SET LOCAL TIME ZONE 'UTC'")
        await target.execute("SET LOCAL TIME ZONE 'UTC'")
        await source.execute(f"SET LOCAL search_path TO {origin}, public")
        await target.execute(f"SET LOCAL search_path TO {destination}, public")
        await target.execute("SET LOCAL lock_timeout = '5s'")
        await target.execute(
            "LOCK TABLE "
            + ",".join(
                f'{destination}."{table}"'
                for table in (*TABLES, "idempotency_keys", "atlas_schema_versions")
            )
            + " IN ACCESS EXCLUSIVE MODE"
        )
        if await target.fetchval(
            f"SELECT array_agg(version ORDER BY version) FROM {destination}.atlas_schema_versions"
        ) != [1]:
            raise ValueError("Target must contain only the initialized graph schema")
        for table in (*TABLES, "idempotency_keys"):
            if await target.fetchval(
                f'SELECT EXISTS (SELECT 1 FROM {destination}."{table}")'
            ):
                raise ValueError("Target graph tables must be empty")
        # Project dedupe triggers populate a companion table during inserts.
        # Restore both tables from the same snapshot with those user triggers
        # suspended; foreign-key and uniqueness constraints remain enforced.
        await target.execute(f"ALTER TABLE {destination}.nodes DISABLE TRIGGER USER")
        for table in TABLES:
            columns = [
                row[0]
                for row in await target.fetch(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema=$1 AND table_name=$2 ORDER BY ordinal_position",
                    target_schema,
                    table,
                )
            ]
            if any(not re.fullmatch(r"[a-z_][a-z0-9_]*", column) for column in columns):
                raise ValueError("Unexpected target column identifier")
            source_columns = {
                row[0]
                for row in await source.fetch(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema=$1 AND table_name=$2",
                    source_schema,
                    table,
                )
            }
            if not set(columns) <= source_columns:
                raise ValueError(f"Source graph schema is incompatible: {table}")
            pairs = ",".join(f"'{column}',t.\"{column}\"" for column in columns)
            where = ""
            if table == "users":
                if tuple(columns) != PROFILE:
                    raise ValueError("Unexpected profile cache schema")
                pairs = ",".join(
                    f"'{column}',"
                    + (
                        "t.user_id::text || '@atlas.invalid'"
                        if column == "email"
                        else f't."{column}"'
                    )
                    for column in columns
                )
                where = " WHERE " + " OR ".join(
                    f'EXISTS (SELECT 1 FROM {origin}."{name}" r WHERE r."{column}"::text=t.user_id::text)'
                    for name, column in REFERENCES
                )
            records = await source.fetch(
                f'SELECT jsonb_build_object({pairs}) FROM {origin}."{table}" t{where}'
            )
            rows = [row[0] for row in records]
            if rows:
                quoted = ",".join(f'"{column}"' for column in columns)
                await target.execute(
                    f'INSERT INTO {destination}."{table}" ({quoted}) SELECT {quoted} FROM jsonb_populate_recordset(NULL::{destination}."{table}", $1::jsonb)',
                    "[" + ",".join(rows) + "]",
                )
            restored = [
                row[0]
                for row in await target.fetch(
                    f'SELECT to_jsonb(t) FROM {destination}."{table}" t'
                )
            ]
            expected = fingerprint(rows)
            if len(rows) != len(restored) or expected != fingerprint(restored):
                raise ValueError(f"Graph transfer verification failed: {table}")
            report["tables"][table] = {"rows": len(rows), "sha256": expected}
            for column in columns:
                sequence = await target.fetchval(
                    "SELECT pg_get_serial_sequence($1,$2)",
                    f'{destination}."{table}"',
                    column,
                )
                if sequence:
                    maximum = await target.fetchval(
                        f'SELECT MAX("{column}") FROM {destination}."{table}"'
                    )
                    await target.execute(
                        "SELECT setval($1::regclass,$2,$3)",
                        sequence,
                        maximum or 1,
                        maximum is not None,
                    )
        await target.execute(f"ALTER TABLE {destination}.nodes ENABLE TRIGGER USER")
    return report


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-env", default="ATLAS_TRANSFER_SOURCE")
    parser.add_argument("--target-env", default="ATLAS_TRANSFER_TARGET")
    parser.add_argument("--source-schema", default="public")
    parser.add_argument("--target-schema", default="public")
    args = parser.parse_args()
    source_dsn = os.environ[args.source_env]
    target_dsn = os.environ[args.target_env]
    for dsn in (source_dsn, target_dsn):
        parsed = urlsplit(dsn)
        if parsed.hostname not in {
            "localhost",
            "127.0.0.1",
            "::1",
        } or not parsed.path.startswith("/atlas_graph_"):
            raise ValueError(
                "This rehearsal command accepts isolated local atlas_graph_* databases only"
            )
    source = await asyncpg.connect(source_dsn)
    try:
        target = await asyncpg.connect(target_dsn)
        try:
            print(
                json.dumps(
                    await transfer(
                        source,
                        target,
                        source_schema=args.source_schema,
                        target_schema=args.target_schema,
                    ),
                    indent=2,
                )
            )
        finally:
            await target.close()
    finally:
        await source.close()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
