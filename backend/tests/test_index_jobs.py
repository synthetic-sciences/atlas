"""Exercise durable indexing and recovery on real SQLite and PostgreSQL stores."""

import asyncio
from datetime import datetime, timezone
import json
import os
import sys
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from fastapi import HTTPException
import pytest
import pytest_asyncio

from atlas_graph.db.connection import close_db, get_db, init_db
from atlas_graph.runtime import Host, configure
from atlas_graph.services import retrieval_service as retrieval
from atlas_graph.services.index_jobs import Indexer


@pytest_asyncio.fixture(params=["sqlite", "postgres"])
async def storage(request, tmp_path, monkeypatch):
    configure(Host())
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ATLAS_MODE", "local")
    monkeypatch.delenv("ATLAS_DATABASE_URL", raising=False)
    admin = None
    name = f"atlas_graph_index_{uuid4().hex}"
    if request.param == "postgres":
        dsn = os.environ.get("ATLAS_TEST_PG_DSN")
        if not dsn:
            pytest.skip("An isolated graph PostgreSQL database is required")
        parsed = urlsplit(dsn)
        assert parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        assert parsed.path.startswith("/atlas_graph_")
        import asyncpg

        admin = await asyncpg.connect(dsn)
        await admin.execute(f'CREATE DATABASE "{name}"')
        monkeypatch.setenv("ATLAS_DATABASE_URL", urlunsplit(parsed._replace(path=f"/{name}")))
    try:
        await init_db()
        yield request.param
    finally:
        configure(Host())
        await close_db()
        if admin is not None:
            await admin.execute(f'DROP DATABASE "{name}"')
            await admin.close()


async def commit(db, node: str, revision: int = 1, operation: str = "atlas_commit_node"):
    await db.execute(
        "INSERT INTO audit_events (event_id,node_id,operation,result_revision,timestamp) VALUES (?,?,?,?,?)",
        (str(uuid4()), node, operation, revision, datetime.now(timezone.utc).isoformat()),
    )


async def seed(*, title: str = "Evidence", committed: bool = True) -> str:
    owner, node = str(uuid4()), str(uuid4())
    now = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        await db.execute("INSERT INTO users (user_id,email,created_at,updated_at) VALUES (?,?,?,?)", (owner, f"{owner}@atlas.invalid", now, now))
        await db.execute("INSERT INTO nodes (node_id,owner_user_id,title,revision,created_at,updated_at) VALUES (?,?,?,1,?,?)", (node, owner, title, now, now))
        if committed:
            await commit(db, node)
        await db.commit()
    return node


async def job(node):
    async with get_db() as db:
        return retrieval._row_to_dict(await retrieval._fetchone(db, "SELECT * FROM atlas_index_jobs WHERE node_id=?", (node,)))


async def rows(node):
    async with get_db() as db:
        return await retrieval._fetchall(db, "SELECT * FROM knowledge_chunks WHERE node_id=? ORDER BY ordinal", (node,))


@pytest.fixture
def provider():
    state = {"calls": 0, "failure": None, "callback": None}

    async def index(node, chunks):
        state["calls"] += 1
        call = state["calls"]
        if state["callback"] is not None:
            await state["callback"]()
        if state["failure"] is not None:
            raise HTTPException(state["failure"], detail="private provider diagnostics must not persist")
        return [[call / 100] * 1536 for _ in chunks]

    configure(Host(index=index))
    try:
        yield state
    finally:
        configure(Host())


async def test_commit_outbox_survives_restart_and_completes_once(storage, provider):
    node = await seed()
    assert (await job(node))["status"] == "pending"
    await close_db()
    await init_db()
    assert await Indexer().run_once() is True
    assert (await job(node))["status"] == "complete"
    assert len(await rows(node)) == 1
    assert await Indexer().run_once() is False
    assert provider["calls"] == 1


async def test_outbox_is_atomic_with_audit_and_ignores_noncommit_events(storage):
    node = await seed(committed=False)
    async with get_db() as db:
        with pytest.raises(ValueError, match="rollback"):
            async with retrieval._index_write(db):
                await commit(db, node)
                raise ValueError("rollback")
        await commit(db, node, operation="stage_update")
        await db.commit()
    assert not await job(node)
    async with get_db() as db:
        await commit(db, node, 3, "thesis_commit_node")
        await commit(db, node, 1, "flywheel_commit_node")
        await db.commit()
    assert (await job(node))["revision"] == 3
    assert (await job(node))["generation"] == 2


async def test_existing_vectors_are_not_rebilled_by_backfill(storage, provider):
    node = await seed()
    async with get_db() as db:
        assert await retrieval.embed_node(db, node) == 1
    original = (await rows(node))[0]["chunk_id"]
    assert provider["calls"] == 1
    assert await Indexer().run_once()
    assert provider["calls"] == 1
    assert (await job(node))["status"] == "complete"
    assert (await rows(node))[0]["chunk_id"] == original


async def test_only_one_leader_dispatches_even_with_multiple_workers(storage, provider):
    node = await seed()
    entered, release = asyncio.Event(), asyncio.Event()

    async def pause():
        entered.set()
        await release.wait()

    provider["callback"] = pause
    first = asyncio.create_task(Indexer().run_once())
    try:
        await asyncio.wait_for(entered.wait(), 5)
        assert await Indexer().run_once() is False
    finally:
        release.set()
        await first
    assert provider["calls"] == 1
    assert (await job(node))["status"] == "complete"


async def test_expired_worker_cannot_publish_or_clear_replacement_job(storage, provider):
    node = await seed()
    entered, release = asyncio.Event(), asyncio.Event()

    async def pause():
        provider["callback"] = None
        entered.set()
        await release.wait()

    provider["callback"] = pause
    first = asyncio.create_task(Indexer().run_once())
    try:
        await asyncio.wait_for(entered.wait(), 5)
        async with get_db() as db:
            await db.execute("UPDATE atlas_index_leader SET lease_until=0")
            await db.execute("UPDATE atlas_index_jobs SET lease_until=0 WHERE node_id=?", (node,))
            await db.commit()
        assert await Indexer().run_once()
        assert json.loads((await rows(node))[0]["embedding"])[0] == .02
    finally:
        release.set()
        await first
    assert (await job(node))["status"] == "complete"
    assert json.loads((await rows(node))[0]["embedding"])[0] == .02


async def test_commit_during_embedding_preserves_latest_generation(storage, provider):
    node = await seed()

    async def change():
        provider["callback"] = None
        async with get_db() as db:
            await db.execute("UPDATE nodes SET title='New evidence',revision=2 WHERE node_id=?", (node,))
            await commit(db, node, 2)
            await db.commit()

    provider["callback"] = change
    assert await Indexer().run_once()
    current = await job(node)
    assert current["status"] == "pending" and current["generation"] == 2 and current["attempt"] == 0
    assert not await rows(node)
    assert await Indexer().run_once()
    assert (await job(node))["status"] == "complete"
    assert (await rows(node))[0]["chunk_text"] == "New evidence"


@pytest.mark.parametrize("code,status", [(402, "blocked"), (403, "blocked"), (503, "pending"), (429, "pending"), (410, "failed")])
async def test_failed_dispatch_retains_durable_recovery_policy(storage, provider, code, status):
    node = await seed()
    provider["failure"] = code
    assert await Indexer().run_once()
    current = await job(node)
    assert current["status"] == status
    assert current["attempt"] == 1 and current["lease_token"] == ""
    assert "private" not in current["last_error"]
    provider["failure"] = None
    assert await Indexer().run_once() is False
    async with get_db() as db:
        await db.execute("UPDATE atlas_index_jobs SET next_run=0 WHERE node_id=?", (node,))
        await db.commit()
    if code == 410:
        assert await Indexer().run_once() is False
        assert provider["calls"] == 1
    else:
        assert await Indexer().run_once()
        assert (await job(node))["status"] == "complete"


async def test_empty_text_removes_previous_chunks_without_paid_dispatch(storage, provider):
    node = await seed()
    assert await Indexer().run_once()
    async with get_db() as db:
        await db.execute("UPDATE nodes SET title='',revision=2 WHERE node_id=?", (node,))
        await commit(db, node, 2)
        await db.commit()
    assert await Indexer().run_once()
    assert not await rows(node)
    assert (await job(node))["status"] == "complete"
    assert provider["calls"] == 1


async def test_shutdown_cancels_dispatch_and_leaves_recoverable_job(storage, provider):
    node = await seed()
    entered = asyncio.Event()

    async def pause():
        entered.set()
        await asyncio.Future()

    provider["callback"] = pause
    worker = Indexer(poll=.01)
    await worker.start()
    await asyncio.wait_for(entered.wait(), 5)
    await asyncio.wait_for(worker.stop(), 5)
    current = await job(node)
    assert current["status"] == "pending" and current["lease_token"] == ""
    async with get_db() as db:
        await db.execute("UPDATE atlas_index_jobs SET next_run=0 WHERE node_id=?", (node,))
        await db.commit()
    provider["callback"] = None
    assert await Indexer().run_once()
    assert (await job(node))["status"] == "complete"


async def test_deleted_node_removes_queued_work(storage, provider):
    node = await seed()
    async with get_db() as db:
        await db.execute("DELETE FROM nodes WHERE node_id=?", (node,))
        await db.commit()
    assert not await job(node)
    assert await Indexer().run_once() is False
    assert provider["calls"] == 0


async def test_retryable_jobs_are_not_dropped_after_five_attempts(storage, provider):
    node = await seed()
    provider["failure"] = 503
    for attempt in range(1, 8):
        assert await Indexer().run_once()
        current = await job(node)
        assert current["status"] == "pending" and current["attempt"] == attempt
        async with get_db() as db:
            await db.execute("UPDATE atlas_index_jobs SET next_run=0 WHERE node_id=?", (node,))
            await db.commit()
    provider["failure"] = None
    assert await Indexer().run_once()
    assert (await job(node))["status"] == "complete"


async def test_chunk_replacement_and_job_acknowledgement_commit_atomically(storage, provider):
    node = await seed()
    assert await Indexer().run_once()
    original = (await rows(node))[0]["chunk_id"]
    async with get_db() as db:
        await db.execute("UPDATE nodes SET title='New evidence',revision=2 WHERE node_id=?", (node,))
        await commit(db, node, 2)
        if storage == "postgres":
            await db.execute("CREATE FUNCTION fixture_index_ack() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.status='complete' THEN RAISE EXCEPTION 'fixture ack failure'; END IF; RETURN NEW; END $$")
            await db.execute("CREATE TRIGGER fixture_index_ack BEFORE UPDATE ON atlas_index_jobs FOR EACH ROW EXECUTE FUNCTION fixture_index_ack()")
        else:
            await db.execute("CREATE TRIGGER fixture_index_ack BEFORE UPDATE ON atlas_index_jobs WHEN NEW.status='complete' BEGIN SELECT RAISE(ABORT,'fixture ack failure'); END")
        await db.commit()
    assert await Indexer().run_once()
    assert (await job(node))["status"] == "pending"
    assert (await rows(node))[0]["chunk_id"] == original
    async with get_db() as db:
        await db.execute("DROP TRIGGER fixture_index_ack" + (" ON atlas_index_jobs" if storage == "postgres" else ""))
        await db.execute("UPDATE atlas_index_jobs SET next_run=0 WHERE node_id=?", (node,))
        await db.commit()
    assert await Indexer().run_once()
    assert (await job(node))["status"] == "complete"
    assert (await rows(node))[0]["chunk_text"] == "New evidence"


async def test_leases_renew_while_provider_is_waiting(storage, provider):
    node = await seed()
    entered, release = asyncio.Event(), asyncio.Event()

    async def pause():
        entered.set()
        await release.wait()

    provider["callback"] = pause
    process = asyncio.create_task(Indexer(lease=3).run_once())
    try:
        await asyncio.wait_for(entered.wait(), 5)
        original = (await job(node))["lease_until"]
        for attempt in range(20):
            await asyncio.sleep(.1)
            if (await job(node))["lease_until"] > original:
                break
        else:
            pytest.fail("The active job lease was not renewed")
        assert await Indexer().run_once() is False
    finally:
        release.set()
        await process
    assert (await job(node))["status"] == "complete"
    assert provider["calls"] == 1


async def test_v1_upgrade_is_atomic_across_processes_and_backfills_only_commits(storage, provider):
    node = await seed(committed=False)
    draft = await seed(committed=False)
    async with get_db() as db:
        await db.execute("DROP TRIGGER atlas_queue_commit" + (" ON audit_events" if storage == "postgres" else ""))
        await db.execute("DROP TABLE atlas_index_jobs")
        await db.execute("DROP TABLE atlas_index_leader")
        await db.execute("DELETE FROM atlas_schema_versions WHERE version=2")
        await commit(db, node)
        await commit(db, draft, operation="stage_update")
        await db.commit()
        assert await retrieval.embed_node(db, node) == 1
    await close_db()
    script = "import asyncio\nfrom atlas_graph.db.connection import init_db,close_db\nasync def run():\n await init_db()\n await close_db()\nasyncio.run(run())"
    processes = [await asyncio.create_subprocess_exec(sys.executable, "-c", script, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE) for _ in range(2)]
    for process in processes:
        _, error = await process.communicate()
        assert process.returncode == 0, error.decode()
    await init_db()
    assert (await job(node))["status"] == "pending"
    assert not await job(draft)
    assert await Indexer().run_once()
    assert provider["calls"] == 1
    async with get_db() as db:
        versions = await retrieval._fetchall(db, "SELECT version FROM atlas_schema_versions ORDER BY version", ())
    assert [row["version"] for row in versions] == [1, 2]


async def test_hard_kill_preserves_claim_until_lease_expiry(storage, provider, tmp_path):
    node = await seed()
    marker = tmp_path / "provider-accepted"
    script = """import asyncio, pathlib, sys
from atlas_graph.db.connection import init_db
from atlas_graph.runtime import Host, configure
from atlas_graph.services.index_jobs import Indexer
async def index(node,chunks):
 pathlib.Path(sys.argv[1]).write_text('accepted')
 await asyncio.Future()
async def run():
 configure(Host(index=index))
 await init_db()
 await Indexer().run_once()
asyncio.run(run())
"""
    process = await asyncio.create_subprocess_exec(sys.executable, "-c", script, str(marker), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        for attempt in range(250):
            if marker.exists():
                break
            if process.returncode is not None:
                _, error = await process.communicate()
                pytest.fail(error.decode())
            await asyncio.sleep(.02)
        else:
            pytest.fail("Child worker did not dispatch")
    finally:
        if process.returncode is None:
            process.kill()
        await process.wait()
    current = await job(node)
    assert current["status"] == "running" and current["lease_token"]
    assert await Indexer().run_once() is False
    async with get_db() as db:
        await db.execute("UPDATE atlas_index_jobs SET lease_until=0 WHERE node_id=?", (node,))
        await db.execute("UPDATE atlas_index_leader SET lease_until=0")
        await db.commit()
    assert await Indexer().run_once()
    assert (await job(node))["status"] == "complete"
    assert len(await rows(node)) == 1


async def test_api_lifespan_runs_indexing_only_when_enabled(storage, provider, monkeypatch):
    from atlas_graph.main import app

    node = await seed()
    monkeypatch.setenv("ATLAS_INDEXING_ENABLED", "false")
    async with app.router.lifespan_context(app):
        await asyncio.sleep(.02)
        assert (await job(node))["status"] == "pending"
        assert provider["calls"] == 0
    monkeypatch.setenv("ATLAS_INDEXING_ENABLED", "true")
    async with app.router.lifespan_context(app):
        for attempt in range(100):
            if (await job(node))["status"] == "complete":
                break
            await asyncio.sleep(.02)
        else:
            pytest.fail("The API lifespan did not start its indexing worker")
    assert provider["calls"] == 1
    assert not any(task.get_name() == "atlas-index-jobs" for task in asyncio.all_tasks())
