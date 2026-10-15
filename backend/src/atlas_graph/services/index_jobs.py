"""Durable commit indexing with database leases and fenced result delivery."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import logging
import math
from uuid import uuid4

from fastapi import HTTPException

from atlas_graph import config
from atlas_graph.db.connection import get_db
from atlas_graph.services import retrieval_service as retrieval

logger = logging.getLogger(__name__)


def _now() -> str:
    return (
        "CAST(EXTRACT(EPOCH FROM clock_timestamp()) AS BIGINT)"
        if config.USE_POSTGRES
        else "CAST(strftime('%s','now') AS INTEGER)"
    )


async def _execute(db, sql: str, params: tuple = ()) -> None:
    cursor = await db.execute(sql, params)
    await cursor.close()


def _json(value):
    return json.loads(value) if isinstance(value, str) else value


def _current(rows, chunks) -> bool:
    if len(rows) != len(chunks):
        return False
    for ordinal, (row, chunk) in enumerate(zip(rows, chunks)):
        if row["ordinal"] != ordinal or row["chunk_text"] != chunk["text"]:
            return False
        try:
            if _json(row["metadata"]) != chunk["metadata"]:
                return False
            vector = _json(row["embedding"])
            if not isinstance(vector, list) or len(vector) != 1536:
                return False
            if any(type(value) not in (int, float) or not math.isfinite(value) for value in vector):
                return False
        except (TypeError, ValueError, OverflowError):
            return False
    return True


@dataclass(frozen=True)
class Job:
    node: str
    generation: int
    attempt: int
    fence: str
    leader: str


class Indexer:
    def __init__(self, *, lease: int = 60, poll: float = 2):
        if lease < 3 or poll <= 0:
            raise ValueError("Index leases and polling intervals must be positive")
        self.lease = lease
        self.poll = poll
        self._lock = asyncio.Lock()
        self._runner: asyncio.Task | None = None

    async def start(self) -> None:
        if self._runner is None or self._runner.done():
            self._runner = asyncio.create_task(self._run(), name="atlas-index-jobs")

    async def stop(self) -> None:
        runner = self._runner
        self._runner = None
        if runner is None:
            return
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)

    async def _run(self) -> None:
        while True:
            try:
                worked = await self.run_once()
            except Exception as error:
                # Provider and database errors may contain credentials or text.
                logger.warning("Index scheduler interrupted (%s)", type(error).__name__)
                worked = False
            await asyncio.sleep(0 if worked else self.poll)

    async def _acquire(self, token: str) -> bool:
        now = _now()
        async with get_db() as db, retrieval._index_write(db):
            await _execute(
                db,
                f"INSERT INTO atlas_index_leader (singleton,token,lease_until) VALUES (1,?,{now}+?) "
                "ON CONFLICT(singleton) DO UPDATE SET token=excluded.token,lease_until=excluded.lease_until "
                f"WHERE atlas_index_leader.lease_until<={now}",
                (token, self.lease),
            )
            row = await retrieval._fetchone(db, "SELECT token FROM atlas_index_leader WHERE singleton=1", ())
            return row is not None and row["token"] == token

    async def _claim(self, leader: str) -> Job | None:
        now = _now()
        fence = uuid4().hex
        async with get_db() as db, retrieval._index_write(db):
            await _execute(
                db,
                f"UPDATE atlas_index_jobs SET status='running',attempt=attempt+1,lease_token=?,lease_until={now}+?,updated_at={now} "
                "WHERE node_id=(SELECT node_id FROM atlas_index_jobs WHERE "
                f"(status IN ('pending','blocked') AND next_run<={now}) OR (status='running' AND lease_until<={now}) "
                "ORDER BY next_run,updated_at,node_id LIMIT 1) "
                f"AND EXISTS (SELECT 1 FROM atlas_index_leader WHERE singleton=1 AND token=? AND lease_until>{now})",
                (fence, self.lease, leader),
            )
            row = await retrieval._fetchone(
                db, "SELECT node_id,generation,attempt FROM atlas_index_jobs WHERE lease_token=? AND status='running'", (fence,)
            )
            return Job(str(row["node_id"]), row["generation"], row["attempt"], fence, leader) if row else None

    async def _owned(self, db, job: Job) -> bool:
        now = _now()
        lock = " FOR UPDATE" if config.USE_POSTGRES else ""
        leader = await retrieval._fetchone(
            db,
            f"SELECT token FROM atlas_index_leader WHERE singleton=1 AND token=? AND lease_until>{now}{lock}",
            (job.leader,),
        )
        if leader is None:
            return False
        row = await retrieval._fetchone(
            db,
            f"SELECT generation FROM atlas_index_jobs WHERE node_id=? AND status='running' AND lease_token=? AND lease_until>{now}{lock}",
            (job.node, job.fence),
        )
        return row is not None and row["generation"] == job.generation

    async def _finish(self, db, job: Job, status: str, error: str = "", delay: int = 0) -> None:
        now = _now()
        await _execute(
            db,
            "UPDATE atlas_index_jobs SET "
            "status=CASE WHEN generation=? THEN ? ELSE 'pending' END,"
            "attempt=CASE WHEN generation=? THEN attempt ELSE 0 END,"
            f"next_run=CASE WHEN generation=? THEN {now}+? ELSE 0 END,"
            "last_error=CASE WHEN generation=? THEN ? ELSE '' END,"
            f"lease_token='',lease_until=0,updated_at={now} "
            "WHERE node_id=? AND status='running' AND lease_token=?",
            (job.generation, status, job.generation, job.generation, delay, job.generation, error, job.node, job.fence),
        )

    async def _prepare(self, db, job: Job) -> bool:
        async with retrieval._index_write(db):
            row = await retrieval._fetchone(
                db,
                "SELECT node_id,owner_user_id,revision,title,summary,content,hypothesis,insights FROM nodes WHERE node_id=?"
                + (" FOR UPDATE" if config.USE_POSTGRES else ""),
                (job.node,),
            )
            if row is None or not await self._owned(db, job):
                return True
            chunks = retrieval._node_chunks(retrieval._row_to_dict(row))
            rows = await retrieval._fetchall(
                db,
                "SELECT chunk_text,embedding,metadata,ordinal FROM knowledge_chunks WHERE node_id=? ORDER BY ordinal",
                (job.node,),
            )
            if chunks and not _current(rows, chunks):
                return False
            if not chunks:
                await _execute(db, "DELETE FROM knowledge_chunks WHERE node_id=?", (job.node,))
            await self._finish(db, job, "complete")
            return True

    async def _process(self, job: Job) -> None:
        async with get_db() as db:
            if await self._prepare(db, job):
                return

            async def guard(connection):
                return await self._owned(connection, job)

            async def complete(connection):
                await self._finish(connection, job, "complete")

            await retrieval.embed_node(db, job.node, guard=guard, complete=complete)

    async def _heartbeat(self, job: Job, process: asyncio.Task, lost: asyncio.Event) -> None:
        try:
            while True:
                await asyncio.sleep(min(10, self.lease / 3))
                now = _now()
                async with get_db() as db, retrieval._index_write(db):
                    await _execute(
                        db,
                        f"UPDATE atlas_index_leader SET lease_until={now}+? WHERE singleton=1 AND token=? AND lease_until>{now}",
                        (self.lease, job.leader),
                    )
                    await _execute(
                        db,
                        f"UPDATE atlas_index_jobs SET lease_until={now}+? WHERE node_id=? AND status='running' AND lease_token=? AND lease_until>{now} "
                        f"AND EXISTS (SELECT 1 FROM atlas_index_leader WHERE singleton=1 AND token=? AND lease_until>{now})",
                        (self.lease, job.node, job.fence, job.leader),
                    )
                    row = await retrieval._fetchone(
                        db,
                        f"SELECT node_id FROM atlas_index_jobs WHERE node_id=? AND status='running' AND lease_token=? AND lease_until>{now} "
                        f"AND EXISTS (SELECT 1 FROM atlas_index_leader WHERE singleton=1 AND token=? AND lease_until>{now})",
                        (job.node, job.fence, job.leader),
                    )
                    if row is None:
                        break
        except Exception as error:
            logger.warning("Index lease renewal interrupted (%s)", type(error).__name__)
        lost.set()
        process.cancel()

    async def run_once(self) -> bool:
        async with self._lock:
            leader = uuid4().hex
            if not await self._acquire(leader):
                return False
            job = None
            heartbeat = None
            try:
                job = await self._claim(leader)
                if job is None:
                    return False
                lost = asyncio.Event()
                process = asyncio.create_task(self._process(job), name="atlas-index-node")
                heartbeat = asyncio.create_task(self._heartbeat(job, process, lost), name="atlas-index-lease")
                try:
                    await process
                except asyncio.CancelledError:
                    if not lost.is_set():
                        raise
                except Exception as error:
                    code = error.status_code if isinstance(error, HTTPException) else 503
                    policies = {
                        400: ("failed", "index_request_invalid"),
                        401: ("blocked", "index_authorization_unavailable"),
                        402: ("blocked", "index_funding_unavailable"),
                        403: ("blocked", "index_authorization_unavailable"),
                        404: ("blocked", "index_authorization_unavailable"),
                        409: ("blocked", "index_funding_unavailable"),
                        410: ("failed", "index_result_expired"),
                        422: ("failed", "index_request_invalid"),
                    }
                    status, reason = policies.get(code, ("pending", "index_temporarily_unavailable"))
                    delay = 300 if status == "blocked" else min(300, 5 * 2 ** min(job.attempt - 1, 6))
                    async with get_db() as db, retrieval._index_write(db):
                        await self._finish(db, job, status, reason, delay)
                return True
            finally:
                if heartbeat is not None:
                    heartbeat.cancel()
                    await asyncio.gather(heartbeat, return_exceptions=True)
                async with get_db() as db, retrieval._index_write(db):
                    if job is not None:
                        await self._finish(db, job, "pending", "index_interrupted", 5)
                    await _execute(db, "DELETE FROM atlas_index_leader WHERE singleton=1 AND token=?", (leader,))
