"""
Background indexer worker for Knowledge v0.

Listens for committed-node signals (fed from the audit log hook), batches them,
and calls ``retrieval_service.embed_nodes`` to produce embeddings in the
background.  Runs as an ``asyncio`` task owned by the FastAPI lifespan.

Design properties
-----------------
* **Batching**: flush when the queue reaches ``IDX_BATCH_SIZE`` nodes OR
  ``IDX_DEBOUNCE_SECONDS`` elapse since the first queued node in a batch,
  whichever comes first.
* **Retries**: on 5xx / timeout errors from the embedder, exponential backoff
  up to ``IDX_MAX_RETRIES`` attempts with ``IDX_MAX_BACKOFF_SECONDS`` cap.
  Exhausted batches are dropped to a dead-letter log line (ERROR) so ops can
  replay manually.
* **Circuit breaker**: after ``IDX_CIRCUIT_FAILURE_THRESHOLD`` consecutive
  *exhausted* batches, the worker pauses for
  ``IDX_CIRCUIT_RESET_SECONDS`` before trying again.
* **Graceful shutdown**: ``stop()`` flips a stop flag, signals the queue,
  awaits the in-flight batch to finish, then cancels the runner.

Env / config knobs (all optional, sensible defaults):

* ``IDX_BATCH_SIZE``             default 100
* ``IDX_DEBOUNCE_SECONDS``       default 10
* ``IDX_MAX_RETRIES``            default 5
* ``IDX_MAX_BACKOFF_SECONDS``    default 60
* ``IDX_BACKOFF_BASE_SECONDS``   default 1
* ``IDX_CIRCUIT_FAILURE_THRESHOLD`` default 10
* ``IDX_CIRCUIT_RESET_SECONDS``  default 300  (5 min)

The worker treats the retrieval service as an opaque dependency that exposes
``async def embed_nodes(node_ids: list[str]) -> None``.  If the service only
exposes ``embed_node`` (singular), the worker will fall back to calling it
per-node inside the batch.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable

logger = logging.getLogger("indexer")


# ---------------------------------------------------------------------------
# Errors the worker classifies as retryable.  Callers / mock services can
# raise any of these to trigger exponential backoff.
# ---------------------------------------------------------------------------


class TransientEmbedError(Exception):
    """Transient failure (HTTP 5xx, timeout, rate-limit).  Will be retried."""


class PermanentEmbedError(Exception):
    """Permanent failure (HTTP 4xx other than 429).  Batch is dropped."""


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass
class IndexerConfig:
    batch_size: int = field(default_factory=lambda: _env_int("IDX_BATCH_SIZE", 100))
    debounce_seconds: float = field(
        default_factory=lambda: _env_float("IDX_DEBOUNCE_SECONDS", 10.0)
    )
    max_retries: int = field(default_factory=lambda: _env_int("IDX_MAX_RETRIES", 5))
    max_backoff_seconds: float = field(
        default_factory=lambda: _env_float("IDX_MAX_BACKOFF_SECONDS", 60.0)
    )
    backoff_base_seconds: float = field(
        default_factory=lambda: _env_float("IDX_BACKOFF_BASE_SECONDS", 1.0)
    )
    circuit_failure_threshold: int = field(
        default_factory=lambda: _env_int("IDX_CIRCUIT_FAILURE_THRESHOLD", 10)
    )
    circuit_reset_seconds: float = field(
        default_factory=lambda: _env_float("IDX_CIRCUIT_RESET_SECONDS", 300.0)
    )
    # Used by tests to make backoff deterministic (no jitter).
    backoff_jitter: bool = True


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


class IndexerWorker:
    """Background worker that embeds committed nodes in batches.

    Parameters
    ----------
    retrieval_service : Any
        Object exposing either ``async embed_nodes(ids)`` or
        ``async embed_node(id)``.
    config : IndexerConfig | None
        Override defaults.  When ``None``, values are pulled from env.
    db_pool : Any
        Reserved for future use (e.g., polling audit table).  The audit-hook
        integration path does not require a DB connection, so this can be
        ``None`` for v0.
    clock : Callable[[], float] | None
        Monotonic clock, overridable for tests.
    sleeper : Callable[[float], Awaitable[None]] | None
        Async sleep function, overridable for tests to fast-forward time.
    """

    def __init__(
        self,
        db_pool: Any = None,
        retrieval_service: Any = None,
        config: IndexerConfig | None = None,
        *,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._db_pool = db_pool
        self._retrieval = retrieval_service
        self._config = config or IndexerConfig()

        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task | None = None

        # Circuit breaker state
        self._consecutive_failures = 0
        self._circuit_open_until: float = 0.0

        # Observability hooks (tests can inspect)
        self.batches_flushed = 0
        self.nodes_embedded = 0
        self.batches_dropped = 0
        self.retry_attempts = 0
        self.circuit_trips = 0

        # Dedup inside a single batch window
        self._seen_in_batch: set[str] = set()

        # Inject-able clock + sleeper so tests can fast-forward without
        # relying on ``freezegun`` (not in the test dependency set).
        self._clock = clock or asyncio.get_event_loop().time
        self._sleeper = sleeper or asyncio.sleep

        # Signals pending-batch drain for graceful shutdown
        self._inflight_lock = asyncio.Lock()

    # --------------------------- public API ---------------------------

    async def start(self) -> None:
        """Start the background runner.  Called from FastAPI lifespan."""
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(
            self._run_forever(), name="indexer-worker"
        )
        logger.info(
            "indexer started (batch_size=%d debounce=%.1fs)",
            self._config.batch_size,
            self._config.debounce_seconds,
        )

    async def stop(self) -> None:
        """Signal shutdown and await the in-flight batch.

        Drains any queued items into a final batch, processes it, then
        returns.  Safe to call multiple times.
        """
        if self._task is None:
            return
        self._stop_event.set()
        # Nudge the runner out of a blocking ``queue.get``.
        await self._queue.put(_SENTINEL)
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None
        logger.info(
            "indexer stopped (flushed=%d embedded=%d dropped=%d)",
            self.batches_flushed,
            self.nodes_embedded,
            self.batches_dropped,
        )

    async def enqueue(self, node_id: str) -> None:
        """Public API: put a node in the queue for embedding.

        Non-blocking from the caller's perspective; safe to call from any
        coroutine (e.g., the audit log hook).
        """
        if not node_id:
            return
        await self._queue.put(node_id)

    # --------------------------- core loop ----------------------------

    async def _run_forever(self) -> None:
        """Loop: drain the queue into batches with debounce + circuit."""
        try:
            while not self._stop_event.is_set():
                # Circuit breaker: if tripped, wait until reset.
                now = self._clock()
                if self._circuit_open_until > now:
                    wait = self._circuit_open_until - now
                    logger.error(
                        "indexer circuit-breaker open; sleeping %.1fs", wait
                    )
                    try:
                        await asyncio.wait_for(
                            self._stop_event.wait(), timeout=wait
                        )
                        break  # shutdown requested while paused
                    except asyncio.TimeoutError:
                        pass
                    self._consecutive_failures = 0
                    self._circuit_open_until = 0.0

                batch = await self._collect_batch()
                if not batch:
                    continue

                async with self._inflight_lock:
                    await self._process_batch(batch)
        except asyncio.CancelledError:
            raise
        except Exception:  # pragma: no cover - runner must never crash silently
            logger.exception("indexer runner crashed")
            raise
        finally:
            # Drain any remaining queue items on shutdown into a final batch.
            remaining = self._drain_queue()
            if remaining:
                async with self._inflight_lock:
                    await self._process_batch(remaining)

    # ------------------------ batch collection ------------------------

    async def _collect_batch(self) -> list[str]:
        """Collect up to ``batch_size`` node ids with debounce window."""
        batch: list[str] = []
        self._seen_in_batch.clear()

        # Wait (potentially forever) for the first item.
        try:
            first = await self._queue.get()
        except asyncio.CancelledError:
            raise
        if first is _SENTINEL:
            return []  # shutdown nudge
        if first not in self._seen_in_batch:
            batch.append(first)
            self._seen_in_batch.add(first)

        deadline = self._clock() + self._config.debounce_seconds

        while (
            len(batch) < self._config.batch_size
            and not self._stop_event.is_set()
        ):
            remaining = deadline - self._clock()
            if remaining <= 0:
                break
            try:
                nxt = await asyncio.wait_for(
                    self._queue.get(), timeout=remaining
                )
            except asyncio.TimeoutError:
                break
            if nxt is _SENTINEL:
                # Shutdown nudge: flush whatever we have.
                break
            if nxt in self._seen_in_batch:
                continue
            batch.append(nxt)
            self._seen_in_batch.add(nxt)

        return batch

    def _drain_queue(self) -> list[str]:
        """Non-blocking drain of remaining items on shutdown."""
        items: list[str] = []
        seen: set[str] = set()
        while True:
            try:
                item = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if item is _SENTINEL:
                continue
            if item in seen:
                continue
            items.append(item)
            seen.add(item)
        return items

    # ------------------------ batch processing ------------------------

    async def _process_batch(self, batch: list[str]) -> None:
        """Call the retrieval service with retries + circuit tracking."""
        attempt = 0
        while True:
            try:
                await self._call_embedder(batch)
                self.batches_flushed += 1
                self.nodes_embedded += len(batch)
                self._consecutive_failures = 0
                logger.info(
                    "indexer flushed batch (size=%d total_embedded=%d)",
                    len(batch),
                    self.nodes_embedded,
                )
                return
            except PermanentEmbedError as exc:
                logger.error(
                    "indexer permanent error (batch=%d): %s -- dropping",
                    len(batch),
                    exc,
                )
                self.batches_dropped += 1
                self._note_failure()
                return
            except (TransientEmbedError, asyncio.TimeoutError) as exc:
                attempt += 1
                self.retry_attempts += 1
                if attempt > self._config.max_retries:
                    logger.error(
                        "indexer dead-letter (batch=%d attempts=%d): %s",
                        len(batch),
                        attempt - 1,
                        exc,
                    )
                    self.batches_dropped += 1
                    self._note_failure()
                    return
                delay = self._compute_backoff(attempt)
                logger.warning(
                    "indexer retry %d/%d in %.2fs (%s)",
                    attempt,
                    self._config.max_retries,
                    delay,
                    exc,
                )
                await self._sleeper(delay)
            except Exception as exc:
                # Treat any other exception as a transient error for retry
                # purposes, but log loudly.
                attempt += 1
                self.retry_attempts += 1
                logger.warning(
                    "indexer unexpected error -- treating as transient (%s)",
                    exc,
                )
                if attempt > self._config.max_retries:
                    logger.error(
                        "indexer dead-letter after unexpected errors "
                        "(batch=%d): %s",
                        len(batch),
                        exc,
                    )
                    self.batches_dropped += 1
                    self._note_failure()
                    return
                delay = self._compute_backoff(attempt)
                await self._sleeper(delay)

    async def _call_embedder(self, batch: list[str]) -> None:
        """Dispatch the batch to the retrieval service."""
        if self._retrieval is None:
            raise PermanentEmbedError("no retrieval service configured")

        # Prefer a batch method if the service exposes one.
        batch_fn = getattr(self._retrieval, "embed_nodes", None)
        if callable(batch_fn):
            await batch_fn(batch)
            return

        single_fn = getattr(self._retrieval, "embed_node", None)
        if callable(single_fn):
            for node_id in batch:
                await single_fn(node_id)
            return

        raise PermanentEmbedError(
            "retrieval service exposes neither embed_nodes nor embed_node"
        )

    # ------------------------ circuit breaker -------------------------

    def _note_failure(self) -> None:
        self._consecutive_failures += 1
        if (
            self._consecutive_failures
            >= self._config.circuit_failure_threshold
        ):
            self._circuit_open_until = (
                self._clock() + self._config.circuit_reset_seconds
            )
            self.circuit_trips += 1
            logger.error(
                "indexer circuit-breaker tripped after %d failures; "
                "paused for %.0fs",
                self._consecutive_failures,
                self._config.circuit_reset_seconds,
            )

    # ---------------------------- backoff -----------------------------

    def _compute_backoff(self, attempt: int) -> float:
        base = self._config.backoff_base_seconds * (2 ** (attempt - 1))
        delay = min(base, self._config.max_backoff_seconds)
        if self._config.backoff_jitter:
            # Full jitter: avoids thundering-herd across replicas
            delay = random.uniform(0.0, delay)
        return delay


# ---------------------------------------------------------------------------
# Internal sentinel pushed onto the queue by ``stop()`` to unblock ``get``.
# ---------------------------------------------------------------------------


class _Sentinel:
    __slots__ = ()


_SENTINEL: Any = _Sentinel()


# ---------------------------------------------------------------------------
# Audit-log hook glue
# ---------------------------------------------------------------------------


# The audit-log hook needs a way to reach the running worker without a hard
# import cycle.  ``app.main`` sets this reference during the FastAPI lifespan.
_active_indexer: IndexerWorker | None = None

# Set of audit operation names that should trigger indexing.
COMMIT_OPERATIONS: frozenset[str] = frozenset(
    {
        "atlas_commit_node",
        "atlas_commit_new_node",
        "thesis_commit_node",
        "thesis_commit_new_node",
        "flywheel_commit_node",
        "flywheel_commit_new_node",
        "commit_node",
    }
)


def set_active_indexer(worker: IndexerWorker | None) -> None:
    """Register (or clear) the running indexer for the audit hook."""
    global _active_indexer
    _active_indexer = worker


def get_active_indexer() -> IndexerWorker | None:
    return _active_indexer


async def notify_commit(operation: str, node_id: str | None) -> None:
    """Forward a commit event to the indexer, if one is attached.

    Called by ``audit_service.log_event`` after a successful commit-shaped
    audit row is written.  Silently no-ops if the indexer isn't running
    (``ENABLE_KNOWLEDGE_INDEXING`` off) or if the node id is missing.
    """
    if not node_id:
        return
    if operation not in COMMIT_OPERATIONS:
        return
    indexer = _active_indexer
    if indexer is None:
        return
    try:
        await indexer.enqueue(node_id)
    except Exception:
        logger.exception("indexer enqueue failed (node_id=%s)", node_id)
