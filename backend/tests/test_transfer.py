"""Exercise transfer safety and post-transfer writes on real, disposable PG16."""

import asyncio
import json
import os
from importlib.resources import files
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest
import pytest_asyncio

asyncpg = pytest.importorskip("asyncpg")

from atlas_graph.ops.transfer import TABLES, transfer

pytestmark = pytest.mark.skipif(
    not os.environ.get("ATLAS_TEST_PG_DSN"),
    reason="An isolated graph PostgreSQL database is required",
)


@pytest_asyncio.fixture
async def databases():
    parsed = urlsplit(os.environ["ATLAS_TEST_PG_DSN"])
    assert parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    assert parsed.path.startswith("/atlas_graph_")
    admin = await asyncpg.connect(urlunsplit(parsed))
    names = [f"atlas_graph_transfer_{uuid4().hex}" for _ in range(3)]
    connections = []
    try:
        for name in names:
            await admin.execute(f'CREATE DATABASE "{name}"')
            connection = await asyncpg.connect(
                urlunsplit(parsed._replace(path=f"/{name}"))
            )
            connections.append(connection)
            await connection.execute(
                files("atlas_graph.db").joinpath("schema.pg.sql").read_text()
            )
            await connection.execute(
                "CREATE TABLE atlas_schema_versions (version integer PRIMARY KEY); INSERT INTO atlas_schema_versions VALUES (1),(2)"
            )
            await connection.execute(files("atlas_graph.db").joinpath("index.pg.sql").read_text())
        yield connections
    finally:
        for connection in connections:
            await connection.close()
        for name in names:
            await admin.execute(f'DROP DATABASE IF EXISTS "{name}"')
        await admin.close()


async def seed(connection):
    owner, reader, unused, root, child = [uuid4() for _ in range(5)]
    await connection.execute(
        "ALTER TABLE users ADD COLUMN password_hash text, ADD COLUMN github_access_token text"
    )
    for user in (owner, reader, unused):
        await connection.execute(
            "INSERT INTO users (user_id,email,display_name,created_at,updated_at,password_hash,github_access_token) VALUES ($1,$2,'Researcher',now(),now(),'disposable-password-hash','disposable-oauth-token')",
            user,
            f"{user}@private.example",
        )
    for table in (
        "api_keys",
        "organizations",
        "credit_transactions",
        "telemetry_events",
    ):
        await connection.execute(f"CREATE TABLE {table} (private_value text)")
        await connection.execute(
            f"INSERT INTO {table} VALUES ('disposable-private-platform-data')"
        )
    await connection.execute(
        "INSERT INTO idempotency_keys VALUES ('opaque-platform-hash','request','{\"api_key\":\"disposable-account-key\"}',201,now(),now()+interval '1 day')"
    )
    await connection.execute(
        "INSERT INTO competitions (competition_id,slug,title) VALUES ('competition','fixture','Fixture')"
    )
    await connection.execute(
        "INSERT INTO nodes (node_id,owner_user_id,title,external_transcript_ref,revision,semantic_data,run_data,created_at) VALUES ($1,$2,'Graph root','atlas-project-dedupe:fixture',7,$3::jsonb,$4::jsonb,'2026-01-02T03:04:05.123456Z')",
        root,
        owner,
        json.dumps({"claim": {"value": 0.123456789012345, "unicode": "λ"}}),
        json.dumps({"history": [1, 2, 3]}),
    )
    await connection.execute(
        "INSERT INTO nodes (node_id,owner_user_id,title,lifecycle,node_type) VALUES ($1,$2,'Child','committed','empirical')",
        child,
        owner,
    )
    await connection.execute(
        "INSERT INTO node_edges (id,parent_id,child_id) VALUES (97,$1,$2)", root, child
    )
    await connection.execute(
        "INSERT INTO artifacts (node_id,artifact_type,title,storage_path,storage_url,size_bytes,payload) VALUES ($1,'binary','Evidence','artifacts/fixture/result.bin','https://private.example/fixture',123,'{\"metric\":0.125}')",
        child,
    )
    await connection.execute(
        "INSERT INTO audit_events (actor_user_id,node_id,operation,result_revision) VALUES ($1,$2,'update',7)",
        owner,
        root,
    )
    await connection.execute(
        "INSERT INTO campaign_budgets (budget_id,root_node_id,organizer_user_id,participant_user_id) VALUES ('budget',$1,$2,$3)",
        str(root),
        owner,
        reader,
    )
    await connection.execute(
        "INSERT INTO competition_entries (entry_id,competition_id,root_node_id,user_id,score) VALUES ('entry','competition',$1,$2,0.125)",
        str(root),
        str(reader),
    )
    await connection.execute(
        "INSERT INTO graph_stars (id,root_node_id,user_id) VALUES (98,$1,$2)",
        root,
        reader,
    )
    await connection.execute(
        "INSERT INTO knowledge_sources (source_id,owner_user_id,source_type) VALUES ('source',$1,'document')",
        owner,
    )
    await connection.execute(
        "INSERT INTO knowledge_chunks (source_id,node_id,chunk_text,embedding,ordinal) VALUES ('source',$1,'Claim λ',$2::vector,0)",
        child,
        json.dumps([0.125] * 1536),
    )
    await connection.execute(
        "INSERT INTO node_access_rules (id,node_id,user_id,access_level) VALUES (99,$1,$2,'read')",
        root,
        reader,
    )
    await connection.execute(
        "INSERT INTO research_log (project_id,entry_type,title,refs,created_by) VALUES ($1,'note','Preserved log',$2::jsonb,'fixture')",
        root,
        json.dumps([str(child)]),
    )
    await connection.execute(
        "INSERT INTO stage_leases (user_id,node_id,expected_revision,expires_at) VALUES ($1,$2,7,now()+interval '1 hour')",
        owner,
        root,
    )
    await connection.execute(
        "INSERT INTO tags (tag_id,root_node_id,name,track_history,history_next_index) VALUES ('tag',$1,'Evidence',true,2)",
        root,
    )
    await connection.execute(
        "INSERT INTO tag_assignments (id,tag_id,node_id) VALUES (100,'tag',$1)", child
    )
    await connection.execute(
        "INSERT INTO tag_history (id,tag_id,node_id,history_index) VALUES (101,'tag',$1,1)",
        child,
    )
    await connection.execute(
        "INSERT INTO artifact_upload_batches (batch_token,node_id,expected_revision,items,expires_at) VALUES ('batch',$1,7,'[{\"name\":\"pending.bin\"}]',now()+interval '1 hour')",
        root,
    )
    await connection.execute(
        "UPDATE nodes SET semantic_data=semantic_data || '{\"precise\": 0.123456789012345678901234567890123456789}'::jsonb WHERE node_id=$1",
        root,
    )
    return owner, reader, unused, root, child


async def test_transfer_preserves_graph_and_excludes_private_platform_data(databases):
    source, target, rollback = databases
    owner, reader, unused, root, child = await seed(source)
    before = await source.fetchval("SELECT jsonb_agg(to_jsonb(t))::text FROM users t")
    report = await transfer(source, target)
    assert set(report["tables"]) == set(TABLES)
    assert all(table["rows"] > 0 for table in report["tables"].values())
    assert report["production_ready"] is False
    assert await target.fetchval("SELECT COUNT(*) FROM users") == 2
    assert (
        await target.fetchval("SELECT email FROM users WHERE user_id=$1", owner)
        == f"{owner}@atlas.invalid"
    )
    assert not await target.fetchval(
        "SELECT EXISTS (SELECT 1 FROM users WHERE user_id=$1)", unused
    )
    assert await target.fetchval("SELECT COUNT(*) FROM idempotency_keys") == 0
    assert not await target.fetchval(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='password_hash')"
    )
    assert (
        await target.fetchval("SELECT revision FROM nodes WHERE node_id=$1", root) == 7
    )
    assert (
        await target.fetchval(
            "SELECT semantic_data->>'precise' FROM nodes WHERE node_id=$1", root
        )
        == "0.123456789012345678901234567890123456789"
    )
    assert (
        await target.fetchval(
            "SELECT storage_path FROM artifacts WHERE node_id=$1", child
        )
        == "artifacts/fixture/result.bin"
    )
    assert (
        await target.fetchval("SELECT vector_dims(embedding) FROM knowledge_chunks")
        == 1536
    )
    assert (
        await target.fetchval(
            "SELECT access_level FROM node_access_rules WHERE user_id=$1", reader
        )
        == "read"
    )
    assert before == await source.fetchval(
        "SELECT jsonb_agg(to_jsonb(t))::text FROM users t"
    )
    assert await source.fetchval("SELECT COUNT(*) FROM idempotency_keys") == 1
    assert "disposable-" not in json.dumps(report)
    for table in (
        "api_keys",
        "organizations",
        "credit_transactions",
        "telemetry_events",
    ):
        assert await target.fetchval("SELECT to_regclass($1)", table) is None

    # Continue writing on the restored graph, then transfer that state back to a
    # third fresh graph database. A rollback must retain writes after cutover.
    added = await target.fetchval(
        "INSERT INTO nodes (owner_user_id,title,external_transcript_ref) VALUES ($1,'New write','atlas-project-dedupe:new') RETURNING node_id",
        owner,
    )
    assert (
        await target.fetchval(
            "SELECT project_id FROM project_dedupe_keys WHERE dedupe_marker='atlas-project-dedupe:new'"
        )
        == added
    )
    assert (
        await target.fetchval(
            "INSERT INTO node_edges (parent_id,child_id) VALUES ($1,$2) RETURNING id",
            root,
            added,
        )
        == 98
    )
    assert (
        await target.fetchval(
            "INSERT INTO graph_stars (root_node_id,user_id) VALUES ($1,$2) RETURNING id",
            added,
            owner,
        )
        == 99
    )
    assert (
        await target.fetchval(
            "INSERT INTO node_access_rules (node_id,user_id,access_level) VALUES ($1,$2,'write') RETURNING id",
            added,
            reader,
        )
        == 100
    )
    assert (
        await target.fetchval(
            "INSERT INTO tag_assignments (tag_id,node_id) VALUES ('tag',$1) RETURNING id",
            added,
        )
        == 101
    )
    assert (
        await target.fetchval(
            "INSERT INTO tag_history (tag_id,node_id,history_index) VALUES ('tag',$1,2) RETURNING id",
            added,
        )
        == 102
    )
    await target.execute(
        "UPDATE nodes SET title='Edited after transfer',revision=8 WHERE node_id=$1",
        root,
    )
    await target.execute(
        "DELETE FROM artifact_upload_batches WHERE batch_token='batch'"
    )
    reverse = await transfer(target, rollback)
    assert reverse["tables"]["nodes"]["rows"] == 3
    assert (
        await rollback.fetchval("SELECT title FROM nodes WHERE node_id=$1", root)
        == "Edited after transfer"
    )
    assert await rollback.fetchval("SELECT COUNT(*) FROM artifact_upload_batches") == 0
    assert (
        await rollback.fetchval(
            "SELECT project_id FROM project_dedupe_keys WHERE dedupe_marker='atlas-project-dedupe:new'"
        )
        == added
    )
    assert (
        await source.fetchval("SELECT revision FROM nodes WHERE node_id=$1", root) == 7
    )


async def test_transfer_refuses_existing_target_and_source_identity(databases):
    source, target, _ = databases
    owner, *_ = await seed(source)
    with pytest.raises(ValueError, match="different databases"):
        await transfer(source, source)
    await target.execute(
        "INSERT INTO users VALUES ($1,'existing@atlas.invalid',null,null,null,now(),now(),null)",
        owner,
    )
    with pytest.raises(ValueError, match="must be empty"):
        await transfer(source, target)
    assert await target.fetchval("SELECT COUNT(*) FROM users") == 1
    assert await target.fetchval("SELECT COUNT(*) FROM nodes") == 0


async def test_transfer_refuses_private_target_schema(databases):
    source, target, _ = databases
    await target.execute("CREATE TABLE api_keys (secret text)")
    with pytest.raises(ValueError, match="only the initialized graph schema"):
        await transfer(source, target)


async def test_transfer_rebuilds_pending_index_work_without_copying_leases(databases):
    source, target, _ = databases
    owner, _, _, root, child = await seed(source)
    await source.execute(
        "INSERT INTO audit_events (actor_user_id,node_id,operation,result_revision) VALUES ($1,$2,'atlas_commit_node',7)",
        owner, root,
    )
    await source.execute(
        "UPDATE atlas_index_jobs SET status='running',attempt=9,lease_token='disposable-stale-job',lease_until=9999999999 WHERE node_id=$1",
        root,
    )
    await source.execute("INSERT INTO atlas_index_leader VALUES (1,'disposable-stale-leader',9999999999)")
    report = await transfer(source, target)
    assert report["scheduler"] == {"source": "commit audit", "queued_nodes": 1, "leases_copied": False}
    restored = await target.fetchrow("SELECT status,attempt,lease_token,lease_until,revision FROM atlas_index_jobs WHERE node_id=$1", root)
    assert tuple(restored) == ("pending", 0, "", 0, 7)
    assert not await target.fetchval("SELECT EXISTS (SELECT 1 FROM atlas_index_jobs WHERE node_id=$1)", child)
    assert await target.fetchval("SELECT COUNT(*) FROM atlas_index_leader") == 0
    assert await source.fetchval("SELECT lease_token FROM atlas_index_jobs WHERE node_id=$1", root) == "disposable-stale-job"


async def test_transfer_between_isolated_schemas_keeps_private_source_data(databases):
    source, _, _ = databases
    owner, *_ = await seed(source)
    parsed = urlsplit(os.environ["ATLAS_TEST_PG_DSN"])
    name = await source.fetchval("SELECT current_database()")
    target = await asyncpg.connect(urlunsplit(parsed._replace(path=f"/{name}")))
    try:
        await target.execute("CREATE SCHEMA graph; SET search_path TO graph,public")
        schema = (
            files("atlas_graph.db")
            .joinpath("schema.pg.sql")
            .read_text()
            .replace("public.", "graph.")
            .replace("graph.vector", "public.vector")
        )
        await target.execute(schema)
        await target.execute(
            "CREATE TABLE graph.atlas_schema_versions (version integer PRIMARY KEY); INSERT INTO graph.atlas_schema_versions VALUES (1),(2)"
        )
        await target.execute(files("atlas_graph.db").joinpath("index.pg.sql").read_text())
        report = await transfer(source, target, target_schema="graph")
        assert report["tables"]["nodes"]["rows"] == 2
        assert await target.fetchval("SELECT COUNT(*) FROM graph.nodes") == 2
        assert await target.fetchval("SELECT COUNT(*) FROM graph.idempotency_keys") == 0
        assert (
            await target.fetchval(
                "SELECT email FROM graph.users WHERE user_id=$1", owner
            )
            == f"{owner}@atlas.invalid"
        )
        assert await source.fetchval("SELECT COUNT(*) FROM public.users") == 3
        assert (
            await source.fetchval("SELECT COUNT(*) FROM public.idempotency_keys") == 1
        )
        assert (
            await source.fetchval(
                "SELECT github_access_token FROM public.users WHERE user_id=$1", owner
            )
            == "disposable-oauth-token"
        )
    finally:
        await target.close()


async def test_failed_transfer_rolls_back_data_and_trigger_changes(databases):
    source, target, _ = databases
    owner, *_ = await seed(source)
    await source.execute(
        "ALTER TABLE artifact_upload_batches RENAME COLUMN items TO incompatible_items"
    )
    with pytest.raises(
        ValueError, match="Source graph schema is incompatible: artifact_upload_batches"
    ):
        await transfer(source, target)
    assert await target.fetchval("SELECT COUNT(*) FROM nodes") == 0
    assert await target.fetchval("SELECT COUNT(*) FROM users") == 0
    assert await target.fetchval(
        "SELECT bool_and(tgenabled='O') FROM pg_trigger WHERE tgrelid='nodes'::regclass AND NOT tgisinternal"
    )
    await target.execute(
        "INSERT INTO users VALUES ($1,'restored@atlas.invalid',null,null,null,now(),now(),null)",
        owner,
    )
    node = await target.fetchval(
        "INSERT INTO nodes (owner_user_id,external_transcript_ref) VALUES ($1,'atlas-project-dedupe:after-failure') RETURNING node_id",
        owner,
    )
    assert (
        await target.fetchval(
            "SELECT project_id FROM project_dedupe_keys WHERE dedupe_marker='atlas-project-dedupe:after-failure'"
        )
        == node
    )


async def test_transfer_uses_one_source_snapshot_during_concurrent_writes(databases):
    source, target, observer = databases
    root = (await seed(source))[3]
    parsed = urlsplit(os.environ["ATLAS_TEST_PG_DSN"])
    name = await source.fetchval("SELECT current_database()")
    writer = await asyncpg.connect(urlunsplit(parsed._replace(path=f"/{name}")))
    try:
        async with writer.transaction():
            await writer.execute(
                "LOCK TABLE artifact_upload_batches IN ACCESS EXCLUSIVE MODE"
            )
            task = asyncio.create_task(transfer(source, target))
            try:

                async def wait_until_copy_reaches_locked_table():
                    while not await observer.fetchval(
                        "SELECT $1::integer = ANY(pg_blocking_pids($2::integer))",
                        writer.get_server_pid(),
                        source.get_server_pid(),
                    ):
                        if task.done():
                            await task
                            pytest.fail(
                                "Transfer completed before reaching the locked source table"
                            )
                        await asyncio.sleep(0.01)

                await asyncio.wait_for(
                    wait_until_copy_reaches_locked_table(), timeout=5
                )
                await writer.execute(
                    "UPDATE nodes SET revision=8 WHERE node_id=$1", root
                )
            except BaseException:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                raise
        await asyncio.wait_for(task, timeout=5)
        assert (
            await target.fetchval("SELECT revision FROM nodes WHERE node_id=$1", root)
            == 7
        )
        assert (
            await source.fetchval("SELECT revision FROM nodes WHERE node_id=$1", root)
            == 8
        )
    finally:
        await writer.close()
